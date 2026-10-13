# ML: the match scorer

No cloud ML service, no GPU. The matcher scores a lost/found pair with a small, explainable model.

**Hard rules run first** (same category, found not more than 1 day before lost, at least one shared word), so the model only ever scores plausible pairs. That is what keeps false positives low.

**Features per pair** (all in 0..1): `text` (word overlap), `location` (same place), `time` (closeness). The scorer also has `image` and `has_image` features (CLIP photo similarity); the **live Supabase matcher does not use them**, so train without `--embed`.

**Default scoring** (no training needed): `0.20 + 0.45*text + 0.20*location + 0.15*time`, suggested at 0.60 or more. It runs inside the database (`../supabase/schema.sql`).

**A trained model is optional.** `train_scorer.py` fits a logistic regression, picks the threshold on a validation split so precision reaches the target (default 0.95), and reports precision, recall, false positives and false negatives on a held-out test split next to the default weights. Splits are by object group, so no object is in both train and test.

`lf_matcher.py` is the Python reference of the scoring. `../supabase/tests/test_schema.py` checks that the SQL version returns the same numbers (default weights and a trained model), so training and serving cannot drift apart.

**Why plain JSON and not a pickle file:** a `.pkl` can execute code when loaded; JSON is only numbers.

## 1. The labelled data
`data/items.csv` has 206 reports: 81 lost/found pairs of the same object (written in different words, places and times) plus 44 reports nobody matched. The unmatched ones matter: they are the lookalikes the scorer must NOT suggest. **This file was written by hand as a realistic stand-in, not collected from students.** Before quoting any number as "real accuracy", add real rows (the columns are documented at the top of `pairs_from_items.py`) and re-run step 2. A good source: every confirmed or dismissed suggestion in the app's `matches` table is a real label.

## 2. Train, evaluate, produce the model
```bash
pip install -r requirements.txt
python fit_final.py data/items.csv          # writes out/weights.json, out/install_model.sql, out/report.md
python cross_validate.py data/items.csv     # optional: repeated cross-validation of the plain train/val/test flow
```
`fit_final.py` scores every pair with a model that never saw either of its objects (out-of-fold), picks the lowest threshold that reaches 95% precision, then fits the final model on everything. `out/report.md` compares it with the hand-set weights. Read it before installing: if the learned model is not clearly better, keep the defaults.

`train_scorer.py` is the simpler single train/val/test version (needs several hundred reports to be stable). `make_synthetic_pairs.py` only exists to test the pipeline (**synthetic numbers are meaningless, never report them**).

## 2b. Model for the AWS backend
`python make_aws_model.py` copies `out/weights.json` to `out/weights_aws.json` and adds two photo weights (`image` +3.0, `has_image` -0.5). They are **set by hand, not learned**, because the data has no photos. `legacy-aws/backend/deploy.*` uploads this file to S3.

## 3. Install the trained model in Supabase
Open `out/install_model.sql`, copy everything, paste it into the Supabase SQL Editor and run it. It is one statement:
```sql
update public.match_settings set model = $json$<the model as JSON>$json$::jsonb where id = 1;
```
The next report uses it. A malformed model is ignored and the default weights are used. To go back to the defaults: `update public.match_settings set model = null where id = 1;`

Only the database owner (the SQL Editor) can change this table; app users cannot read or write it.
