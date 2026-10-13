"""Builds out/weights_aws.json for the AWS backend: the trained model plus the two PHOTO weights.

The trained weights (text, location, time, bias, threshold) come from fit_final.py. There are no real photo pairs
to learn from yet, so the photo weights are set BY HAND (and the file says so):
  image     +3.0  per 1.0 of label overlap between the two photos
  has_image -0.5  when both reports have a photo (so two photos that share no labels count against the pair)
Replace them with learned weights once real confirmed/dismissed matches with photos exist.

Run:  python make_aws_model.py        (reads out/weights.json, writes out/weights_aws.json)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PHOTO_WEIGHTS = {"image": 3.0, "has_image": -0.5}


def main():
    with open(os.path.join(HERE, "out", "weights.json"), encoding="utf-8") as f:
        model = json.load(f)
    model["weights"].update(PHOTO_WEIGHTS)
    model["photoWeights"] = "hand-set, not learned (no real photo pairs yet)"
    with open(os.path.join(HERE, "out", "weights_aws.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
        f.write("\n")
    print("wrote out/weights_aws.json", model["weights"])


if __name__ == "__main__":
    main()
