"""
test_local_vlm.py — Local Vision-LLM Testing Script
Optimized for Apple Silicon (MPS).
"""
import torch
from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
from PIL import Image
import requests
from io import BytesIO

# 1. Configuration
# Note: Using the 2B parameter version (much smaller than 397B).
# Even this requires ~4.5GB VRAM.
MODEL_ID = "Qwen/Qwen2-VL-2B-Instruct" 

print(f"--- Initializing {MODEL_ID} ---")
print("Targeting Device: MPS (Apple Silicon GPU)")

# 2. Load Model and Processor
# Using bfloat16 for better performance on Mac
model = Qwen2VLForConditionalGeneration.from_pretrained(
    MODEL_ID, 
    torch_dtype=torch.bfloat16, 
    device_map="auto"
)
processor = AutoProcessor.from_pretrained(MODEL_ID)

# 3. Prepare Image and Messages
url = "https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/p-blog/candy.JPG"
response = requests.get(url)
img = Image.open(BytesIO(response.content))

messages = [
    {
        "role": "user",
        "content": [
            {"type": "image", "image": img},
            {"type": "text", "text": "What animal is on the candy?"}
        ]
    },
]

# 4. Process Inputs
text = processor.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)
image_inputs, video_inputs = [], None # Qwen2-VL specific utility would be better but this is the raw transformers way
inputs = processor(
    text=[text],
    images=[img],
    padding=True,
    return_tensors="pt",
)
inputs = inputs.to("mps") # Move to Mac GPU

# 5. Generate
print("--- Generating Response ---")
generated_ids = model.generate(**inputs, max_new_tokens=50)
generated_ids_trimmed = [
    out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
]
output_text = processor.batch_decode(
    generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
)

print("\nRESULT:")
print(output_text[0])
