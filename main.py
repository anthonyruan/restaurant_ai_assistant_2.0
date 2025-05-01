from flask import Flask, render_template, request
from dotenv import load_dotenv
import openai
import requests
import datetime
import os
import base64

load_dotenv()

# === Load environment variables ===

app = Flask(__name__)

# === Set up API clients ===
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID")

# === Get Top 5 Dishes from Square ===
def get_top_dishes():
    today = datetime.datetime.utcnow().date()
    yesterday = today - datetime.timedelta(days=1)
    start_time = f"{yesterday}T00:00:00Z"
    end_time = f"{yesterday}T23:59:59Z"

    url = "https://connect.squareup.com/v2/orders/search"
    headers = {
        "Authorization": f"Bearer {SQUARE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    body = {
        "location_ids": [SQUARE_LOCATION_ID],
        "query": {
            "filter": {
                "date_time_filter": {
                    "created_at": {
                        "start_at": start_time,
                        "end_at": end_time
                    }
                },
                "state_filter": {
                    "states": ["COMPLETED"]
                }
            },
            "sort": {
                "sort_field": "CREATED_AT",
                "sort_order": "DESC"
            }
        }
    }

    response = requests.post(url, headers=headers, json=body)
    data = response.json()

    item_counter = {}
    try:
        for order in data.get("orders", []):
            for line_item in order.get("line_items", []):
                name = line_item.get("name", "Unnamed Item")
                quantity = int(float(line_item.get("quantity", "1")))
                item_counter[name] = item_counter.get(name, 0) + quantity
    except Exception as e:
        print("❌ Error parsing Square orders:", e)
        return [{"name": "⚠️ Error", "sold": 0}]

    top_items = sorted(item_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    return [{"name": name, "sold": count} for name, count in top_items]

# === Generate AI Caption ===
def generate_caption(dish_list):
    prompt = f"Generate an engaging Instagram caption promoting these dishes: {', '.join([d['name'] for d in dish_list])}"
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# === Custom prompts for image generation ===
dish_prompt_overrides = {
    "Sandwich": "Vietnamese Bánh Mì with grilled pork, pickled carrots, cilantro, on a crusty baguette",
    "Pho": "Vietnamese Pho noodle soup with beef, basil, bean sprouts, and lime",
    "Vermicelli": "Vietnamese grilled pork vermicelli bowl with fresh herbs and fish sauce",
    "Spring Roll": "Vietnamese fresh spring rolls with shrimp and vermicelli"
}

# === Generate AI Image ===
def generate_dish_image(dish_name):
    # Use custom prompt if defined
    prompt_base = dish_prompt_overrides.get(dish_name, dish_name)
    prompt = f"A high-quality Instagram-style food photo of {prompt_base}, on a wooden table, studio lighting, delicious and fresh, close-up"
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    return response.data[0].url

# === Flask Route ===
@app.route("/")
def index():
    top_dishes = get_top_dishes()
    caption = generate_caption(top_dishes)
    top_dish_name = top_dishes[0]["name"]
    image_url = generate_dish_image(top_dish_name)

    return render_template("index.html", dishes=top_dishes, caption=caption, image_url=image_url)

# ✅ 上传图片并发帖
@app.route("/post-to-instagram", methods=["POST"])
def post_to_instagram():
    image_url = request.form.get("image_url")
    caption = request.form.get("caption")

    # Step 1: 下载图片内容（转换为 base64 格式）
    image_data = requests.get(image_url).content
    with open("generated_image.jpg", "wb") as f:
        f.write(image_data)

    # Step 2: 上传到 Instagram
    instagram_account_id = os.getenv("IG_USER_ID")
    access_token = os.getenv("IG_ACCESS_TOKEN")

    # 上传图片容器
    image_upload_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media"
    create_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token
    }
    create_res = requests.post(image_upload_url, data=create_payload)
    creation_id = create_res.json().get("id")

    if not creation_id:
        return render_template("index.html", dishes=get_top_dishes(), caption=caption, image_url=image_url, post_status="❌ Failed to create media object.")

    # 发布媒体容器
    publish_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": access_token
    }
    publish_res = requests.post(publish_url, data=publish_payload)

    if publish_res.status_code == 200:
        return render_template("index.html", dishes=get_top_dishes(), caption=caption, image_url=image_url, post_status="✅ Successfully posted to Instagram!")
    else:
        return render_template("index.html", dishes=get_top_dishes(), caption=caption, image_url=image_url, post_status=f"❌ Failed to publish: {publish_res.text}")

# 🔁 Regenerate Caption
@app.route("/regenerate-caption", methods=["POST"])
def regenerate_caption():
    image_url = request.form.get("image_url")
    top_dishes = get_top_dishes()
    caption = generate_caption(top_dishes)
    return render_template("index.html", dishes=top_dishes, caption=caption, image_url=image_url)

# 🔁 Regenerate Image
@app.route("/regenerate-image", methods=["POST"])
def regenerate_image():
    caption = request.form.get("caption")
    top_dishes = get_top_dishes()
    top_dish_name = top_dishes[0]["name"]
    image_url = generate_dish_image(top_dish_name)
    return render_template("index.html", dishes=top_dishes, caption=caption, image_url=image_url)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
