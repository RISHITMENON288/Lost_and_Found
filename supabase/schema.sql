-- =====================================================================================
-- Campus Lost & Found: Supabase schema.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query -> paste this whole file -> Run.
-- It is safe to run again (it never drops your data).
--
-- Security model in one paragraph:
--   * The app talks to Postgres directly through Supabase's API, signed in as the user.
--   * Row Level Security (RLS) decides what each user may read. Nobody can read the settings table.
--   * Clients may only INSERT reports (and only the listed columns). Everything else a client
--     does (close, return, accept/reject a match) goes through the functions below, which check
--     ownership themselves. Matches are created ONLY by the matcher inside the database.
--   * Photos live in a private bucket; users upload into their own folder and read photos only of
--     reports they are allowed to see.
-- =====================================================================================

-- ---------------------------------------------------------------- tables

create table if not exists public.items (
  id            uuid primary key default gen_random_uuid(),
  reporter_id   uuid not null references auth.users (id) on delete cascade,
  reporter_name text not null,
  type          text not null check (type in ('LOST', 'FOUND')),
  category      text not null check (category in (
                  'ELECTRONICS', 'BAG', 'CLOTHING', 'ACCESSORY', 'STATIONERY',
                  'KEYS', 'CONTAINER', 'DOCUMENTS', 'SPORTS', 'TOYS')),
  title         text not null,
  description   text not null default '',
  location      text not null,
  occurred_at   bigint not null,             -- epoch milliseconds, when it was lost/found
  image_path    text,                        -- object path inside the private 'item-photos' bucket
  status        text not null default 'OPEN'
                  check (status in ('OPEN', 'POTENTIAL_MATCH', 'CLAIMED', 'RETURNED', 'CLOSED')),
  created_at    bigint not null default (extract(epoch from clock_timestamp()) * 1000)::bigint
);

create index if not exists items_status_created_idx on public.items (status, created_at desc);
create index if not exists items_reporter_idx       on public.items (reporter_id, created_at desc);
create index if not exists items_candidates_idx     on public.items (category, type, status);

create table if not exists public.matches (
  id                uuid primary key default gen_random_uuid(),
  lost_item_id      uuid not null references public.items (id) on delete cascade,
  found_item_id     uuid not null references public.items (id) on delete cascade,
  lost_reporter_id  uuid not null,
  found_reporter_id uuid not null,
  score             numeric(5, 4) not null,
  state             text not null default 'PENDING' check (state in ('PENDING', 'CONFIRMED', 'REJECTED')),
  created_at        bigint not null default (extract(epoch from clock_timestamp()) * 1000)::bigint,
  unique (lost_item_id, found_item_id)       -- one suggestion per pair, so retries cannot duplicate
);

create index if not exists matches_lost_item_idx  on public.matches (lost_item_id);
create index if not exists matches_found_item_idx on public.matches (found_item_id);
create index if not exists matches_lost_user_idx  on public.matches (lost_reporter_id, created_at desc);
create index if not exists matches_found_user_idx on public.matches (found_reporter_id, created_at desc);

-- Optional trained scorer (see ml/README.md). One row, readable only by the database owner.
create table if not exists public.match_settings (
  id    int primary key check (id = 1),
  model jsonb
);
insert into public.match_settings (id, model) values (1, null) on conflict (id) do nothing;

-- ---------------------------------------------------------------- privileges + row level security
-- Supabase grants broad table rights to its API roles by default; take them away, then give back the minimum.

revoke all on public.items, public.matches, public.match_settings from anon, authenticated;

grant select on public.items to authenticated;
grant insert (type, category, title, description, location, occurred_at, image_path) on public.items to authenticated;
grant select on public.matches to authenticated;

alter table public.items          enable row level security;
alter table public.matches        enable row level security;
alter table public.match_settings enable row level security;   -- no policies = nobody but the owner

drop policy if exists matches_select on public.matches;
create policy matches_select on public.matches for select to authenticated
  using ((select auth.uid()) in (lost_reporter_id, found_reporter_id));

-- A user sees: every open report, their own reports, and any report that appears in one of their matches.
drop policy if exists items_select on public.items;
create policy items_select on public.items for select to authenticated
  using (
    status in ('OPEN', 'POTENTIAL_MATCH')
    or reporter_id = (select auth.uid())
    or exists (
      select 1 from public.matches m
      where (m.lost_item_id = items.id or m.found_item_id = items.id)
        and (select auth.uid()) in (m.lost_reporter_id, m.found_reporter_id)
    )
  );

drop policy if exists items_insert on public.items;
create policy items_insert on public.items for insert to authenticated
  with check (reporter_id = (select auth.uid()));

-- ---------------------------------------------------------------- matching (SQL port of the Python matcher)
-- Hard gates keep false positives down (score 0 if any fails):
--   LOST + FOUND, same category, found not more than 1 day before lost, at least one shared word.
-- Then: 0.20 + 0.45*text + 0.20*location + 0.15*time  (no image feature in this version)
-- or a trained logistic model from public.match_settings. Suggested only at >= 0.60 (or the model's threshold).

create or replace function public.lf_tokens(t text)
returns text[]
language sql immutable parallel safe
set search_path = ''
as $$
  select coalesce(array_agg(distinct w), '{}'::text[])
  from regexp_split_to_table(lower(coalesce(t, '')), '[^a-z0-9]+') as w
  where length(w) > 2
    and w <> all (array['the','and','with','has','have','was','were','near','from','for','this','that',
                        'there','found','lost','left','some','very','into','onto','its','are','not','but',
                        'inside','side'])
$$;

create or replace function public.lf_text_similarity(a text, b text)
returns double precision
language plpgsql immutable parallel safe
set search_path = ''
as $$
declare
  ta text[] := public.lf_tokens(a);
  tb text[] := public.lf_tokens(b);
  common int;
begin
  if cardinality(ta) = 0 or cardinality(tb) = 0 then
    return 0;
  end if;
  select count(*) into common from unnest(ta) as x where x = any (tb);
  return 2.0 * common / (cardinality(ta) + cardinality(tb));
end
$$;

-- Returns the stored model only if it is well formed; otherwise NULL (= use the built-in weights).
create or replace function public.lf_model()
returns jsonb
language plpgsql stable security definer
set search_path = ''
as $$
declare
  m jsonb;
  n text;
begin
  select s.model into m from public.match_settings s where s.id = 1;
  if m is null or m ->> 'type' is distinct from 'logistic' then
    return null;
  end if;
  foreach n in array array['text', 'location', 'time', 'image', 'has_image'] loop
    if (m -> 'weights' ->> n)::double precision is null then
      return null;
    end if;
  end loop;
  if (m ->> 'bias')::double precision is null then
    return null;
  end if;
  perform coalesce((m ->> 'threshold')::double precision, 0.6);
  return m;
exception when others then
  return null;
end
$$;

create or replace function public.lf_threshold(model jsonb)
returns double precision
language sql immutable
set search_path = ''
as $$
  select case when model is null then 0.60
              else coalesce((model ->> 'threshold')::double precision, 0.60) end
$$;

create or replace function public.lf_score(lost public.items, found public.items, model jsonb default null)
returns double precision
language plpgsql immutable
set search_path = ''
as $$
declare
  day_ms constant bigint := 86400000;
  txt double precision;
  loc double precision;
  closeness double precision;
  gap_days double precision;
  z double precision;
begin
  if lost.type <> 'LOST' or found.type <> 'FOUND' then return 0; end if;
  if lost.category <> found.category then return 0; end if;
  if found.occurred_at + day_ms < lost.occurred_at then return 0; end if;

  txt := public.lf_text_similarity(lost.title || ' ' || lost.description, found.title || ' ' || found.description);
  if txt <= 0 then return 0; end if;

  loc := case when lower(lost.location) = lower(found.location) then 1.0 else 0.0 end;
  gap_days := abs(found.occurred_at - lost.occurred_at)::double precision / day_ms;
  closeness := greatest(0.0, 1.0 - least(gap_days / 7.0, 1.0));

  if model is null then
    return 0.20 + 0.45 * txt + 0.20 * loc + 0.15 * closeness;
  end if;

  -- images are not used in this version, so the image features are 0
  z := (model ->> 'bias')::double precision
       + (model -> 'weights' ->> 'text')::double precision * txt
       + (model -> 'weights' ->> 'location')::double precision * loc
       + (model -> 'weights' ->> 'time')::double precision * closeness;
  z := greatest(-30.0, least(30.0, z));
  return 1.0 / (1.0 + exp(-z));
end
$$;

-- Compare one report with every open report of the opposite type; create PENDING suggestions. Idempotent.
create or replace function public.lf_run_matching(p_item uuid)
returns int
language plpgsql security definer
set search_path = ''
as $$
declare
  it public.items;
  o public.items;
  l_item public.items;   -- note: never name a variable "found": it would hide plpgsql's FOUND flag
  f_item public.items;
  model jsonb := public.lf_model();
  thr double precision := public.lf_threshold(public.lf_model());
  v double precision;
  created int := 0;
  inserted int;
begin
  select * into it from public.items where id = p_item;
  if not found or it.status not in ('OPEN', 'POTENTIAL_MATCH') then
    return 0;
  end if;

  for o in
    select * from public.items c
    where c.category = it.category
      and c.type = case it.type when 'LOST' then 'FOUND' else 'LOST' end
      and c.status in ('OPEN', 'POTENTIAL_MATCH')
      and c.reporter_id <> it.reporter_id
    order by c.created_at desc
    limit 500
  loop
    if it.type = 'LOST' then l_item := it; f_item := o; else l_item := o; f_item := it; end if;
    v := public.lf_score(l_item, f_item, model);
    if v >= thr then
      insert into public.matches (lost_item_id, found_item_id, lost_reporter_id, found_reporter_id, score)
      values (l_item.id, f_item.id, l_item.reporter_id, f_item.reporter_id, round(v::numeric, 4))
      on conflict (lost_item_id, found_item_id) do nothing;
      get diagnostics inserted = row_count;
      if inserted > 0 then
        created := created + 1;
        update public.items set status = 'POTENTIAL_MATCH' where id in (l_item.id, f_item.id) and status = 'OPEN';
      end if;
    end if;
  end loop;
  return created;
end
$$;

-- ---------------------------------------------------------------- phone numbers (private)
-- A phone number is saved at sign-up (the app sends it as sign-up metadata). It lives in its own table that
-- NO app user can read directly. The only way out is get_match_contact(), which gives the FINDER's number to
-- the OWNER of the lost item, and only after the owner confirmed the match.

create table if not exists public.profiles (
  user_id uuid primary key references auth.users (id) on delete cascade,
  phone text not null check (phone ~ '^\+?[0-9]{10,15}$')
);
alter table public.profiles enable row level security;
revoke all on public.profiles from anon, authenticated;

create or replace function public.lf_profile_from_signup()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  p text := regexp_replace(coalesce(new.raw_user_meta_data ->> 'phone', ''), '[ ()-]', '', 'g');
begin
  if p ~ '^\+?[0-9]{10,15}$' then
    insert into public.profiles (user_id, phone) values (new.id, p) on conflict (user_id) do nothing;
  end if;
  return new;
exception when others then
  return new; -- a problem with the phone must never block creating the account
end
$$;

drop trigger if exists lf_profile_from_signup on auth.users;
create trigger lf_profile_from_signup after insert on auth.users
  for each row execute function public.lf_profile_from_signup();

create or replace function public.get_match_contact(p_match uuid)
returns text
language plpgsql security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  m public.matches;
  lost_status text;
  number text;
begin
  if uid is null then raise exception 'Please sign in again.' using errcode = 'PT401'; end if;
  select * into m from public.matches where id = p_match;
  if not found or uid not in (m.lost_reporter_id, m.found_reporter_id) then
    raise exception 'Match not found.' using errcode = 'PT404';
  end if;
  if uid <> m.lost_reporter_id then
    raise exception 'Only the owner of the lost item can see the finder''s number.' using errcode = 'PT403';
  end if;
  select i.status into lost_status from public.items i where i.id = m.lost_item_id;
  if m.state <> 'CONFIRMED' or lost_status <> 'CLAIMED' then
    raise exception 'The number is shown after you confirm a match, until the item is returned.' using errcode = 'PT409';
  end if;
  select pr.phone into number from public.profiles pr where pr.user_id = m.found_reporter_id;
  if number is null then
    raise exception 'The finder did not add a phone number.' using errcode = 'PT404';
  end if;
  return number;
end
$$;

-- ---------------------------------------------------------------- validation + matching on every new report

create or replace function public.lf_items_before_insert()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  display text;
  now_ms bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint;
  active int;
begin
  if uid is null then
    raise exception 'Please sign in again.' using errcode = 'PT401';
  end if;

  -- these four never come from the client
  new.reporter_id := uid;
  new.status := 'OPEN';
  new.created_at := now_ms;
  select coalesce(nullif(btrim(u.raw_user_meta_data ->> 'name'), ''), split_part(u.email, '@', 1))
    into display from auth.users u where u.id = uid;
  new.reporter_name := left(coalesce(display, 'Student'), 50);

  if new.type = 'FOUND' and not exists (select 1 from public.profiles pr where pr.user_id = uid) then
    raise exception 'Your account has no phone number. Create a new account with a phone number to report a found item.'
      using errcode = 'PT400';
  end if;

  new.title := btrim(regexp_replace(coalesce(new.title, ''), '[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', 'g'));
  new.description := btrim(regexp_replace(coalesce(new.description, ''), '[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', 'g'));
  if char_length(new.title) < 3 or char_length(new.title) > 60 then
    raise exception 'Title must be 3 to 60 characters.' using errcode = 'PT400';
  end if;
  if char_length(new.description) > 300 then
    raise exception 'Description is too long (max 300).' using errcode = 'PT400';
  end if;
  if new.location is null or new.location <> all (array['Library', 'Main Gate', 'Academic Block', 'Cafeteria',
       'Hostel Area', 'Sports Ground', 'Auditorium', 'Parking', 'Other']) then
    raise exception 'Unknown location.' using errcode = 'PT400';
  end if;
  if new.occurred_at is null or new.occurred_at > now_ms + 300000 then
    raise exception 'The time cannot be in the future.' using errcode = 'PT400';
  end if;
  if new.occurred_at < now_ms - 365::bigint * 86400000 then
    raise exception 'The time is more than a year ago.' using errcode = 'PT400';
  end if;

  if new.image_path is not null then
    if new.image_path !~ ('^' || uid::text || '/[0-9a-f-]{36}\.jpg$') then
      raise exception 'Invalid photo.' using errcode = 'PT400';
    end if;
    if not exists (select 1 from storage.objects o where o.bucket_id = 'item-photos' and o.name = new.image_path) then
      raise exception 'Photo upload was not completed.' using errcode = 'PT400';
    end if;
  end if;

  select count(*) into active from public.items i
    where i.reporter_id = uid and i.status in ('OPEN', 'POTENTIAL_MATCH');
  if active >= 20 then
    raise exception 'You have too many open reports. Close some before adding more.' using errcode = 'PT429';
  end if;
  return new;
end
$$;

drop trigger if exists lf_items_before_insert on public.items;
create trigger lf_items_before_insert before insert on public.items
  for each row execute function public.lf_items_before_insert();

create or replace function public.lf_items_after_insert()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
begin
  begin
    perform public.lf_run_matching(new.id);
  exception when others then
    -- a matching problem must never lose the user's report
    raise warning 'lf_run_matching failed: %', sqlerrm;
  end;
  return new;
end
$$;

drop trigger if exists lf_items_after_insert on public.items;
create trigger lf_items_after_insert after insert on public.items
  for each row execute function public.lf_items_after_insert();

-- ---------------------------------------------------------------- lifecycle (called by the app)

-- A POTENTIAL_MATCH report with no pending suggestion left goes back to OPEN.
create or replace function public.lf_refresh_status(p_item uuid)
returns void
language plpgsql security definer
set search_path = ''
as $$
begin
  update public.items i set status = 'OPEN'
  where i.id = p_item and i.status = 'POTENTIAL_MATCH'
    and not exists (
      select 1 from public.matches m
      where m.state = 'PENDING' and (m.lost_item_id = p_item or m.found_item_id = p_item));
end
$$;

-- Reject the pending suggestions of an item; returns the ids of the OTHER reports that were involved.
create or replace function public.lf_reject_pending_for(p_item uuid)
returns uuid[]
language plpgsql security definer
set search_path = ''
as $$
declare
  others uuid[];
begin
  with u as (
    update public.matches m set state = 'REJECTED'
    where m.state = 'PENDING' and (m.lost_item_id = p_item or m.found_item_id = p_item)
    returning m.lost_item_id, m.found_item_id)
  select coalesce(array_agg(distinct x), '{}'::uuid[]) into others
  from (select lost_item_id as x from u union select found_item_id from u) t
  where x <> p_item;
  return others;
end
$$;

create or replace function public.lf_close(p_item uuid)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  others uuid[] := public.lf_reject_pending_for(p_item);
  o uuid;
begin
  update public.items set status = 'CLOSED' where id = p_item and status in ('OPEN', 'POTENTIAL_MATCH');
  foreach o in array others loop
    perform public.lf_refresh_status(o);
  end loop;
end
$$;

create or replace function public.close_item(p_item uuid)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  it public.items;
begin
  if uid is null then raise exception 'Please sign in again.' using errcode = 'PT401'; end if;
  select * into it from public.items where id = p_item and reporter_id = uid for update;
  if not found then raise exception 'Item not found.' using errcode = 'PT404'; end if;
  if it.status not in ('OPEN', 'POTENTIAL_MATCH') then
    raise exception 'This report can no longer be closed.' using errcode = 'PT409';
  end if;
  perform public.lf_close(p_item);
end
$$;

create or replace function public.mark_returned(p_item uuid)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  it public.items;
  ids uuid[];
begin
  if uid is null then raise exception 'Please sign in again.' using errcode = 'PT401'; end if;
  select * into it from public.items where id = p_item and reporter_id = uid for update;
  if not found then raise exception 'Item not found.' using errcode = 'PT404'; end if;
  if it.status <> 'CLAIMED' then
    raise exception 'Only a claimed item can be marked as returned.' using errcode = 'PT409';
  end if;
  select array_agg(distinct x) into ids from (
    select p_item as x
    union select m.lost_item_id from public.matches m
      where m.state = 'CONFIRMED' and (m.lost_item_id = p_item or m.found_item_id = p_item)
    union select m.found_item_id from public.matches m
      where m.state = 'CONFIRMED' and (m.lost_item_id = p_item or m.found_item_id = p_item)) t;
  update public.items set status = 'RETURNED' where id = any (ids) and status = 'CLAIMED';
end
$$;

-- Only the owner of the LOST item decides. Nothing is ever assigned automatically.
create or replace function public.respond_to_match(p_match uuid, p_confirm boolean)
returns void
language plpgsql security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  m public.matches;
  others uuid[] := '{}';
  o uuid;
begin
  if uid is null then raise exception 'Please sign in again.' using errcode = 'PT401'; end if;
  if p_confirm is null then raise exception 'confirm must be true or false.' using errcode = 'PT400'; end if;
  select * into m from public.matches where id = p_match for update;
  if not found or uid not in (m.lost_reporter_id, m.found_reporter_id) then
    raise exception 'Match not found.' using errcode = 'PT404';
  end if;
  if uid <> m.lost_reporter_id then
    raise exception 'Only the owner of the lost item can respond to a match.' using errcode = 'PT403';
  end if;
  if m.state <> 'PENDING' then
    raise exception 'This match was already answered.' using errcode = 'PT409';
  end if;

  update public.matches set state = case when p_confirm then 'CONFIRMED' else 'REJECTED' end where id = p_match;

  if p_confirm then
    others := public.lf_reject_pending_for(m.lost_item_id) || public.lf_reject_pending_for(m.found_item_id);
    update public.items set status = 'CLAIMED'
      where id in (m.lost_item_id, m.found_item_id) and status in ('OPEN', 'POTENTIAL_MATCH');
  else
    others := array[m.lost_item_id, m.found_item_id];
  end if;
  foreach o in array others loop
    if o not in (m.lost_item_id, m.found_item_id) or not p_confirm then
      perform public.lf_refresh_status(o);
    end if;
  end loop;
end
$$;

-- Housekeeping: close reports nobody resolved. Run it by hand or schedule it (see the end of this file).
create or replace function public.lf_expire_old(p_days int default 60)
returns int
language plpgsql security definer
set search_path = ''
as $$
declare
  cutoff bigint := (extract(epoch from clock_timestamp()) * 1000)::bigint - p_days::bigint * 86400000;
  r record;
  closed int := 0;
begin
  for r in select id from public.items where status in ('OPEN', 'POTENTIAL_MATCH') and created_at < cutoff loop
    perform public.lf_close(r.id);
    closed := closed + 1;
  end loop;
  return closed;
end
$$;

-- Who may call what. Supabase gives API roles EXECUTE on new functions by default; remove it everywhere,
-- then grant only the four functions the app is meant to call.
revoke all on function
  public.lf_tokens(text), public.lf_text_similarity(text, text), public.lf_model(), public.lf_threshold(jsonb),
  public.lf_score(public.items, public.items, jsonb), public.lf_run_matching(uuid),
  public.lf_items_before_insert(), public.lf_items_after_insert(), public.lf_refresh_status(uuid),
  public.lf_reject_pending_for(uuid), public.lf_close(uuid), public.lf_expire_old(int),
  public.lf_profile_from_signup(), public.get_match_contact(uuid),
  public.close_item(uuid), public.mark_returned(uuid), public.respond_to_match(uuid, boolean)
  from public, anon, authenticated;

-- Supabase's sign-up service fires the profile trigger; make sure it is allowed to (harmless if it already is).
do $$
begin
  if exists (select from pg_roles where rolname = 'supabase_auth_admin') then
    grant usage on schema public to supabase_auth_admin;
    grant execute on function public.lf_profile_from_signup() to supabase_auth_admin;
  end if;
end $$;

grant execute on function public.close_item(uuid)                 to authenticated;
grant execute on function public.mark_returned(uuid)              to authenticated;
grant execute on function public.respond_to_match(uuid, boolean)  to authenticated;
grant execute on function public.get_match_contact(uuid)          to authenticated;

-- ---------------------------------------------------------------- photos (private bucket)

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('item-photos', 'item-photos', false, 5242880, array['image/jpeg'])
on conflict (id) do update
  set public = false, file_size_limit = 5242880, allowed_mime_types = array['image/jpeg'];

-- Upload only into your own folder: <your user id>/<random>.jpg. No update/delete policies: files are write-once.
drop policy if exists lf_photos_insert on storage.objects;
create policy lf_photos_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'item-photos' and (storage.foldername(name))[1] = (select auth.uid())::text);

-- Read your own uploads, and photos of reports you are allowed to see (the items policy applies inside).
drop policy if exists lf_photos_select on storage.objects;
create policy lf_photos_select on storage.objects for select to authenticated
  using (
    bucket_id = 'item-photos'
    and (
      (storage.foldername(name))[1] = (select auth.uid())::text
      or exists (select 1 from public.items i where i.image_path = storage.objects.name)
    )
  );

-- Tell the Data API about new/changed functions right away (harmless if nothing changed).
notify pgrst, 'reload schema';

-- ---------------------------------------------------------------- OPTIONAL: daily clean-up
-- Dashboard -> Database -> Extensions -> enable "pg_cron", then run:
--   select cron.schedule('lf-expire', '15 3 * * *', $$select public.lf_expire_old(60)$$);
