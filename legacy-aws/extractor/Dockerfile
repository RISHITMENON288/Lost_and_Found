FROM public.ecr.aws/lambda/python:3.12

# CPU-only PyTorch (the default wheel bundles CUDA and is several GB larger)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the CLIP weights into the image: the Lambda has no internet access.
ENV HF_HOME=/opt/hf
RUN python -c "from transformers import CLIPModel, CLIPProcessor; n='openai/clip-vit-base-patch32'; CLIPModel.from_pretrained(n); CLIPProcessor.from_pretrained(n)"
ENV HF_HUB_OFFLINE=1

COPY features.py app.py ${LAMBDA_TASK_ROOT}/
CMD ["app.handler"]
