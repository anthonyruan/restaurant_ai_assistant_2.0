from flask import Flask, render_template, request
from dotenv import load_dotenv
import openai
import requests
import datetime
import os
import base64
import functools
import time

load_dotenv()

app = Flask(__name__)

# === Load API Keys from Environment ===
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")


def ttl_cache(ttl_seconds):
    def decorator(func):
        cache = {}
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            key = (args, frozenset(kwargs.items()))
            if key in cache:
                value, timestamp = cache[key]
                elapsed = now - timestamp
                remaining = ttl_seconds - elapsed
                if elapsed < ttl_seconds:
                    print(f"📦 Using cached result for {func.__name__}{args} — {remaining:.0f}s remaining")
                    return value
            result = func(*args, **kwargs)
            cache[key] = (result, now)
            print(f"🆕 Cache updated for {func.__name__}{args}")
            return result
        return wrapper
    return decorator

# === Retrieve Top 5 Selling Dishes from Square POS ===
@ttl_cache(ttl_seconds=600)  # 缓存 10 分钟
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


# === Get Current Weather Data for a Given City ===
@ttl_cache(ttl_seconds=600)  # 缓存10分钟
def get_weather(city="New York"):
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=imperial"
    response = requests.get(url)
    if response.status_code != 200:
        print("❌ Failed to fetch weather data:", response.text)
        return None
    data = response.json()
    return {
        "condition": data["weather"][0]["main"],
        "description": data["weather"][0]["description"],
        "temp": data["main"]["temp"]
    }



# === Check if Tomorrow is a Public Holiday (Using Calendarific API) ===
@ttl_cache(ttl_seconds=600)
def get_holiday_info():
    HOLIDAY_API_KEY = os.getenv("HOLIDAY_API_KEY")  # 确保你已在 .env 文件中设置
    country = "US"  # 可改为你的国家
    tomorrow = datetime.datetime.utcnow().date() + datetime.timedelta(days=1)

    # === 查询明天是否为节日 ===
    url = "https://calendarific.com/api/v2/holidays"
    params = {
        "api_key": HOLIDAY_API_KEY,
        "country": country,
        "year": tomorrow.year,
        "month": tomorrow.month,
        "day": tomorrow.day
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        print("❌ Failed to fetch holiday data:", response.text)
        return {"is_holiday": False, "next_holiday_in_days": None, "message": "⚠️ Failed to retrieve holiday info."}

    holidays = response.json().get("response", {}).get("holidays", [])
    if holidays:
        name = holidays[0].get("name", "Holiday")
        return {
            "is_holiday": True,
            "message": f"🎉 Tomorrow is {name}!"
        }

    # === 如果不是节日，查找下一个节日（当前年）===
    upcoming_url = "https://calendarific.com/api/v2/holidays"
    upcoming_params = {
        "api_key": HOLIDAY_API_KEY,
        "country": country,
        "year": tomorrow.year
    }

    upcoming_response = requests.get(upcoming_url, params=upcoming_params)
    if upcoming_response.status_code != 200:
        return {"is_holiday": False, "next_holiday_in_days": None, "message": "⚠️ Failed to retrieve next holiday."}

    all_holidays = upcoming_response.json().get("response", {}).get("holidays", [])

    # 只保留未来的节日
    future_holidays = [h for h in all_holidays if datetime.date.fromisoformat(h["date"]["iso"][:10]) > tomorrow]

    # ✅ 排序保障：确保是最近的排在最前面
    future_holidays.sort(key=lambda h: datetime.date.fromisoformat(h["date"]["iso"][:10]))

    if future_holidays:
        next_holiday = future_holidays[0]
        next_date = datetime.date.fromisoformat(next_holiday["date"]["iso"][:10])
        delta = (next_date - tomorrow).days
        return {
            "is_holiday": False,
            "next_holiday_in_days": delta,
            "message": f"🗓️ Tomorrow is not a holiday. {delta} days left until {next_holiday['name']}."
        }

    return {"is_holiday": False, "next_holiday_in_days": None, "message": "No upcoming holidays found."}

# === Generate Instagram Caption Based on Sales Data ===
def generate_caption(dish_list):
    try:
        top_dish_name = dish_list[0]['name']
        prompt = f"Write an Instagram caption to promote the Vietnamese dish '{top_dish_name}' in an appetizing, fun, and catchy way."
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Error generating caption: {str(e)}"

# === Generate Instagram Caption Based on Weather Conditions ===
def generate_weather_caption():
    weather = get_weather()
    if not weather:
        return "⚠️ Weather data unavailable"
    prompt = (
        f"Write an Instagram caption recommending Vietnamese dishes for a {weather['description']} day "
        f"with a temperature of {weather['temp']}°F. Make it appealing and cozy."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ Error generating weather-based caption: {str(e)}"

# === Image Prompt Overrides for Specific Dishes ===
dish_prompt_overrides = {
    "Sandwich": "Vietnamese Bánh Mì with grilled pork, pickled carrots, cilantro, on a crusty baguette",
    "Pho": "Vietnamese Pho noodle soup with beef, basil, bean sprouts, and lime",
    "Vermicelli": "Vietnamese grilled pork vermicelli bowl with fresh herbs and fish sauce",
    "Spring Roll": "Vietnamese fresh spring rolls with shrimp and vermicelli"
}

# === Generate Dish Image from Top Sales ===
def generate_dish_image(dish_name):
    prompt_base = dish_prompt_overrides.get(dish_name, dish_name)
    prompt = f"A high-quality Instagram-style food photo of {prompt_base}, on a wooden table, studio lighting, delicious and fresh, close-up"
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    return response.data[0].url



# === Generate Dish Image Based on Weather Mood ===
def generate_weather_image():
    weather = get_weather()
    if not weather:
        return "https://via.placeholder.com/400x400.png?text=No+Image"
    prompt = (
        f"A cozy Vietnamese noodle soup served on a {weather['description']} day, steam rising, "
        f"warm lighting, wooden table, comforting feel"
    )
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        return response.data[0].url
    except Exception as e:
        print("⚠️ Error generating weather image:", e)
        return "https://via.placeholder.com/400x400.png?text=Image+Error"

# === Render Homepage with Initial Data (No Image Yet) ===
@app.route("/")
def index():
    top_dishes = get_top_dishes()
    caption = generate_caption(top_dishes)
    top_dish_name = top_dishes[0]["name"]
    image_url = None  # 延迟生成
    weather_image_url = None  # 延迟生成
    holiday_info = get_holiday_info()
    holiday_caption = None
    holiday_image_url = None  # 延迟生成

    # Get tomorrow's weather forecast safely
    try:
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?q=New York&appid={WEATHER_API_KEY}&units=imperial"
        response = requests.get(forecast_url)
        data = response.json()
        tomorrow = datetime.datetime.utcnow().date() + datetime.timedelta(days=1)
        entries = [entry for entry in data["list"] if entry["dt_txt"].startswith(str(tomorrow))]
        if entries:
            mid_entry = entries[len(entries)//2]
            weather_info = f"Tomorrow's weather in New York: {mid_entry['weather'][0]['description'].capitalize()}, {mid_entry['main']['temp']}°F"
        else:
            weather_info = "⚠️ Weather forecast for tomorrow is unavailable."
    except Exception as e:
        print("❌ Error fetching forecast:", e)
        weather_info = "⚠️ Error retrieving weather forecast."

    weather_caption_text = generate_weather_caption()


    if holiday_info["is_holiday"]:
        # 如果是节日，生成节日 caption
        try:
            prompt = f"Tomorrow is {holiday_info['message']}. Write a festive Instagram caption recommending Vietnamese dishes."
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}]
            )
            holiday_caption = response.choices[0].message.content
        except Exception as e:
            holiday_caption = f"⚠️ Error generating holiday caption: {str(e)}"



    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption_text,
        weather_image_url=weather_image_url,
        holiday_message=holiday_info["message"],
        holiday_caption=holiday_caption,
        active_tab="sales"
    )

# === Handle POST: Regenerate Weather-Based Caption Only ===
@app.route("/weather-caption", methods=["POST"])
def regenerate_weather_caption():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")  # ✅ 保留原 caption（基于销量）
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption_text = generate_weather_caption()  # ✅ 只重新生成天气的

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption_text,
        active_tab="weather"
    )

# === Handle POST: Regenerate Sales-Based Caption Only ===
@app.route("/regenerate-caption", methods=["POST"])
def regenerate_sales_caption():
    top_dishes = get_top_dishes()
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    caption = generate_caption(top_dishes)

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        active_tab="sales"
    )

# === Handle POST: Regenerate Sales-Based Dish Image Only ===
@app.route("/regenerate-image", methods=["POST"])
def regenerate_sales_image():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    top_dish_name = top_dishes[0]["name"]
    image_url = generate_dish_image(top_dish_name)

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        active_tab="sales"
    )


# === Handle POST: Publish Sales-Based Content to Instagram ===
@app.route("/post-to-instagram", methods=["POST"])
def post_to_instagram():
    image_url = request.form.get("image_url")
    caption = request.form.get("caption")

    instagram_account_id = os.getenv("IG_USER_ID")
    access_token = os.getenv("IG_ACCESS_TOKEN")

    # Step 1: Download image and save locally
    try:
        image_data = requests.get(image_url).content
        with open("generated_image.jpg", "wb") as f:
            f.write(image_data)
    except Exception as e:
        return render_template("error.html", message=f"❌ Error downloading image: {str(e)}")

    # Step 2: Create media object
    upload_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media"
    upload_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token
    }
    upload_res = requests.post(upload_url, data=upload_payload)
    creation_id = upload_res.json().get("id")

    if not creation_id:
        return render_template("error.html", message="❌ Failed to create media object.")

    # Step 3: Publish media
    publish_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": access_token
    }
    publish_res = requests.post(publish_url, data=publish_payload)

    if publish_res.status_code == 200:
        return render_template("success.html", caption=caption)
    else:
        return render_template("error.html", message=f"❌ Failed to publish: {publish_res.text}")


# === Handle POST: Regenerate Weather-Based Dish Image Only ===
@app.route("/regenerate-weather-image", methods=["POST"])
def regenerate_weather_image():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")

    weather_image_url = generate_weather_image()

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        weather_image_url=weather_image_url,
        active_tab="weather"
    )

# === Handle POST: Publish Weather-Based Content to Instagram ===
@app.route("/post-weather-to-instagram", methods=["POST"])
def post_weather_to_instagram():
    image_url = request.form.get("weather_image_url")
    caption = request.form.get("weather_caption")

    instagram_account_id = os.getenv("IG_USER_ID")
    access_token = os.getenv("IG_ACCESS_TOKEN")

    # Step 1: Download image
    try:
        image_data = requests.get(image_url).content
        with open("weather_generated_image.jpg", "wb") as f:
            f.write(image_data)
    except Exception as e:
        return render_template("error.html", message=f"❌ Error downloading weather image: {str(e)}")

    # Step 2: Upload to Instagram
    upload_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media"
    upload_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token
    }
    upload_res = requests.post(upload_url, data=upload_payload)
    creation_id = upload_res.json().get("id")

    if not creation_id:
        return render_template("error.html", message="❌ Failed to create media object.")

    # Step 3: Publish media
    publish_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": access_token
    }
    publish_res = requests.post(publish_url, data=publish_payload)

    if publish_res.status_code == 200:
        return render_template("success.html", caption=caption)
    else:
        return render_template("error.html", message=f"❌ Failed to publish: {publish_res.text}", active_tab="weather")



# === Handle POST: Regenerate Holiday-Based Dish Image Only ===
@app.route("/regenerate-holiday-image", methods=["POST"])
def regenerate_holiday_image():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    holiday_caption = request.form.get("holiday_caption")

    # 构建节假日图片生成 prompt
    prompt = (
        f"A vibrant Vietnamese dish presented with festive decorations, celebrating a special holiday. "
        f"Studio lighting, warm ambiance, wooden table background, close-up, Instagram style"
    )

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        holiday_image_url = response.data[0].url
    except Exception as e:
        print("❌ Error generating holiday image:", e)
        holiday_image_url = "https://via.placeholder.com/400x400.png?text=Holiday+Image+Error"

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        holiday_caption=holiday_caption,
        holiday_image_url=holiday_image_url,
        active_tab="holiday" 
    )



# === Handle POST: Publish Holiday-Based Content to Instagram ===
@app.route("/post-holiday-to-instagram", methods=["POST"])
def post_holiday_to_instagram():
    image_url = request.form.get("holiday_image_url")
    caption = request.form.get("holiday_caption")

    instagram_account_id = os.getenv("IG_USER_ID")
    access_token = os.getenv("IG_ACCESS_TOKEN")

    # Step 1: 下载图片
    try:
        image_data = requests.get(image_url).content
        with open("holiday_generated_image.jpg", "wb") as f:
            f.write(image_data)
    except Exception as e:
        return render_template("error.html", message=f"❌ Error downloading holiday image: {str(e)}")

    # Step 2: 上传到 Instagram
    upload_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media"
    upload_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token
    }
    upload_res = requests.post(upload_url, data=upload_payload)
    creation_id = upload_res.json().get("id")

    if not creation_id:
        return render_template("error.html", message="❌ Failed to create media object.")

    # Step 3: 发布到 Instagram
    publish_url = f"https://graph.facebook.com/v19.0/{instagram_account_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": access_token
    }
    publish_res = requests.post(publish_url, data=publish_payload)

    if publish_res.status_code == 200:
        return render_template("success.html", caption=caption)
    else:
        return render_template("error.html", message=f"❌ Failed to publish: {publish_res.text}", active_tab="holiday")


# === Handle POST: Regenerate Holiday-Based Caption Only ===
@app.route("/regenerate-holiday-caption", methods=["POST"])
def regenerate_holiday_caption():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")

    holiday_info = get_holiday_info()
    if holiday_info["is_holiday"]:
        try:
            prompt = f"Tomorrow is {holiday_info['message']}. Write a festive Instagram caption recommending Vietnamese dishes."
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}]
            )
            holiday_caption = response.choices[0].message.content
        except Exception as e:
            holiday_caption = f"⚠️ Error generating holiday caption: {str(e)}"
    else:
        holiday_caption = None  # 如果不是节日，保持不变

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        holiday_caption=holiday_caption,
        holiday_message=holiday_info["message"],
        weather_image_url=None,
        holiday_image_url=None,
        active_tab="holiday"
    )

@app.route("/update-top-dishes", methods=["POST"])
def update_top_dishes():
    top_dishes = get_top_dishes()

    # 从页面中保留其他字段
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    weather_image_url = request.form.get("weather_image_url")
    holiday_caption = request.form.get("holiday_caption")
    holiday_message = request.form.get("holiday_message")
    holiday_image_url = request.form.get("holiday_image_url")

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        weather_image_url=weather_image_url,
        holiday_caption=holiday_caption,
        holiday_message=holiday_message,
        holiday_image_url=holiday_image_url
    )


@app.route("/refresh-weather", methods=["POST"])
def refresh_weather():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_caption = request.form.get("weather_caption")
    weather_image_url = request.form.get("weather_image_url")
    holiday_caption = request.form.get("holiday_caption")
    holiday_message = request.form.get("holiday_message")
    holiday_image_url = request.form.get("holiday_image_url")

    # 获取最新天气
    try:
        forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?q=New York&appid={WEATHER_API_KEY}&units=imperial"
        response = requests.get(forecast_url)
        data = response.json()
        tomorrow = datetime.datetime.utcnow().date() + datetime.timedelta(days=1)
        entries = [entry for entry in data["list"] if entry["dt_txt"].startswith(str(tomorrow))]
        if entries:
            mid_entry = entries[len(entries)//2]
            weather_info = f"Tomorrow's weather in New York: {mid_entry['weather'][0]['description'].capitalize()}, {mid_entry['main']['temp']}°F"
        else:
            weather_info = "⚠️ Weather forecast for tomorrow is unavailable."
    except Exception as e:
        print("❌ Error fetching forecast:", e)
        weather_info = "⚠️ Error retrieving weather forecast."

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        weather_image_url=weather_image_url,
        holiday_caption=holiday_caption,
        holiday_message=holiday_message,
        holiday_image_url=holiday_image_url,
        active_tab="weather"
    )

@app.route("/refresh-holiday", methods=["POST"])
def refresh_holiday():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    weather_image_url = request.form.get("weather_image_url")
    holiday_caption = request.form.get("holiday_caption")
    holiday_image_url = request.form.get("holiday_image_url")

    holiday_info = get_holiday_info()

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        weather_image_url=weather_image_url,
        holiday_caption=holiday_caption,
        holiday_message=holiday_info["message"],
        holiday_image_url=holiday_image_url,
        active_tab="holiday"
    )