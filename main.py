from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash, session
from dotenv import load_dotenv
import openai
import uuid
import json
import requests
import datetime
import os
import base64
import functools
import time
from werkzeug.utils import secure_filename
import random  # Add this at the top if not present


UPLOAD_FOLDER = 'static/images/dishes'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
DISH_IMAGE_MAP_PATH = 'dish_image_map.json'
SETTINGS_PATH = "settings.json"





load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = "vietspot2024supersecret"  # 用于session和flash消息

# === Load API Keys from Environment ===
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

UPLOAD_FOLDER = 'static/images/dishes'
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}

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
@ttl_cache(ttl_seconds=600)
def generate_caption(top_dish_name, salt=None):
    try:
        prompt = f"Write an Instagram caption to promote the Vietnamese dish '{top_dish_name}' in an appetizing, fun, and catchy way."
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip() + "\n\n" + get_hashtags()
    except Exception as e:
        return f"⚠️ Error generating caption: {str(e)}\n\n" + get_hashtags()

# === Generate Instagram Caption Based on Weather Conditions ===
@ttl_cache(ttl_seconds=600)
def generate_weather_caption(salt=None):
    weather = get_weather()
    if not weather:
        return "⚠️ Weather data unavailable\n\n" + get_hashtags()
    try:
        with open(DISH_IMAGE_MAP_PATH, 'r') as f:
            dish_image_map = json.load(f)
        dish_list = list(dish_image_map.keys())
    except (FileNotFoundError, json.JSONDecodeError):
        dish_list = []
    if not dish_list:
        dish_list_str = "any delicious Vietnamese dish"
    else:
        dish_list_str = ", ".join(dish_list)
    prompt = (
        f"Write an Instagram caption recommending a dish for a {weather['description']} day "
        f"with a temperature of {weather['temp']}°F. "
        f"IMPORTANT: You MUST choose a dish ONLY from the following list: {dish_list_str}. "
        f"Make the caption appealing and cozy, and mention the chosen dish by name."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip() + "\n\n" + get_hashtags()
    except Exception as e:
        return f"⚠️ Error generating weather-based caption: {str(e)}\n\n" + get_hashtags()

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



# === Render Homepage with Initial Data (No Image Yet) ===
@app.route("/health")
def health_check():
    return "OK", 200

@app.route("/start-edit-caption", methods=["POST"])
def start_edit_caption():
    session['editing_caption'] = True
    return redirect(url_for('index'))

@app.route("/edit-caption", methods=["POST"])
def edit_caption():
    session['edited_caption'] = request.form.get('edited_caption', '').strip()
    session['editing_caption'] = False
    return redirect(url_for('index'))

@app.route("/cancel-edit-caption", methods=["POST"])
def cancel_edit_caption():
    session['editing_caption'] = False
    # 不再清空 session['edited_caption']
    return redirect(url_for('index'))

# Weather Caption 编辑相关路由
@app.route("/start-edit-weather-caption", methods=["POST"])
def start_edit_weather_caption():
    session['editing_weather_caption'] = True
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'weather'
    return redirect(url_for('index', active_tab=active_tab))

@app.route("/edit-weather-caption", methods=["POST"])
def edit_weather_caption():
    session['edited_weather_caption'] = request.form.get('edited_weather_caption', '').strip()
    session['editing_weather_caption'] = False
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'weather'
    return redirect(url_for('index', active_tab=active_tab))

@app.route("/cancel-edit-weather-caption", methods=["POST"])
def cancel_edit_weather_caption():
    session['editing_weather_caption'] = False
    # 不再清空 session['edited_weather_caption']
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'weather'
    return redirect(url_for('index', active_tab=active_tab))

# Holiday Caption 编辑相关路由
@app.route("/start-edit-holiday-caption", methods=["POST"])
def start_edit_holiday_caption():
    session['editing_holiday_caption'] = True
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'holiday'
    return redirect(url_for('index', active_tab=active_tab))

@app.route("/edit-holiday-caption", methods=["POST"])
def edit_holiday_caption():
    session['edited_holiday_caption'] = request.form.get('edited_holiday_caption', '').strip()
    session['editing_holiday_caption'] = False
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'holiday'
    return redirect(url_for('index', active_tab=active_tab))

@app.route("/cancel-edit-holiday-caption", methods=["POST"])
def cancel_edit_holiday_caption():
    session['editing_holiday_caption'] = False
    # 不再清空 session['edited_holiday_caption']
    active_tab = request.form.get('active_tab') or request.args.get('active_tab') or 'holiday'
    return redirect(url_for('index', active_tab=active_tab))

# 修改主页index路由，优先显示用户编辑的weather/holiday caption，并传递editing变量
@app.route("/")
def index():
    import time
    t0 = time.time()
    active_tab = request.args.get('active_tab') or 'sales'
    top_dishes = get_top_dishes()
    print(f"[耗时] 获取销量数据: {time.time() - t0:.2f} 秒")
    for dish in top_dishes:
        dish['image_url'] = get_dish_image(dish['name'])
    t1 = time.time()
    ai_caption = generate_caption(top_dishes[0]['name']) if top_dishes else ""
    caption = session.get('edited_caption', ai_caption)
    editing_caption = session.get('editing_caption', False)
    print(f"[耗时] 生成AI Caption: {time.time() - t1:.2f} 秒")
    image_url = top_dishes[0]['image_url'] if top_dishes else None
    t2 = time.time()
    ai_weather_caption = generate_weather_caption()
    weather_caption = session.get('edited_weather_caption', ai_weather_caption)
    editing_weather_caption = session.get('editing_weather_caption', False)
    print(f"[耗时] 生成天气AI Caption: {time.time() - t2:.2f} 秒")
    t3 = time.time()
    weather_image_url = get_image_from_caption(weather_caption)
    print(f"[耗时] 选取天气图片: {time.time() - t3:.2f} 秒")
    t4 = time.time()
    holiday_info = get_holiday_info()
    print(f"[耗时] 获取节日信息: {time.time() - t4:.2f} 秒")
    ai_holiday_caption = None
    holiday_caption = None
    editing_holiday_caption = session.get('editing_holiday_caption', False)
    t5 = time.time()
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
    print(f"[耗时] 获取明日天气: {time.time() - t5:.2f} 秒")
    t6 = time.time()
    if holiday_info["is_holiday"]:
        ai_holiday_caption = generate_holiday_caption(holiday_info["message"])
        holiday_caption = session.get('edited_holiday_caption', ai_holiday_caption)
        print(f"[耗时] 生成节日AI Caption: {time.time() - t6:.2f} 秒")
    print(f"[耗时] 主页总耗时: {time.time() - t0:.2f} 秒")
    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        weather_image_url=weather_image_url,
        holiday_message=holiday_info["message"],
        holiday_caption=holiday_caption,
        active_tab=active_tab,
        highlight_caption=False,
        editing_caption=editing_caption,
        editing_weather_caption=editing_weather_caption,
        editing_holiday_caption=editing_holiday_caption
    )

# === Handle POST: Regenerate Weather-Based Caption Only ===
@app.route("/weather-caption", methods=["POST"])
def regenerate_weather_caption():
    top_dishes = get_top_dishes()
    caption = request.form.get("caption")
    image_url = request.form.get("image_url")
    weather_info = request.form.get("weather_info")
    weather_image_url = request.form.get("weather_image_url")
    holiday_caption = request.form.get("holiday_caption")
    holiday_message = request.form.get("holiday_message")
    holiday_image_url = request.form.get("holiday_image_url")
    # 清除自定义内容
    session.pop('edited_weather_caption', None)
    weather_caption_text = generate_weather_caption(salt=str(uuid.uuid4()))
    session['edited_weather_caption'] = weather_caption_text  # 新增：同步 session
    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption_text,
        weather_image_url=weather_image_url,
        holiday_caption=holiday_caption,
        holiday_message=holiday_message,
        holiday_image_url=holiday_image_url,
        highlight_weather_caption=True,
        highlight_caption=False,
        active_tab="weather",
        editing_weather_caption=False
    )

# === Handle POST: Regenerate Sales-Based Caption Only ===
@app.route("/regenerate-caption", methods=["POST"])
def regenerate_sales_caption():
    print("DEBUG: Regenerating caption...")
    top_dishes = get_top_dishes()
    for dish in top_dishes:
        dish['image_url'] = get_dish_image(dish['name'])
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    # 清除用户自定义的 caption
    session.pop('edited_caption', None)
    # 传入随机 salt，强制绕过缓存
    caption = generate_caption(top_dishes[0]['name'], salt=str(uuid.uuid4())) if top_dishes else ""
    print(f"DEBUG: New caption is: {caption}")
    session['edited_caption'] = caption  # 新增：同步 session
    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=top_dishes[0]['image_url'] if top_dishes else None,
        weather_info=weather_info,
        weather_caption=weather_caption,
        highlight_caption=True,
        active_tab="sales"
    )

# === Handle POST: Regenerate Sales-Based Dish Image Only ===
@app.route("/regenerate-image", methods=["POST"])
def regenerate_sales_image():
    top_dishes = get_top_dishes()
    for dish in top_dishes:
        dish['image_url'] = get_dish_image(dish['name'])
    caption = request.form.get("caption")
    weather_info = request.form.get("weather_info")
    weather_caption = request.form.get("weather_caption")
    # Always select a new random image for the top dish
    image_url = get_dish_image(top_dishes[0]['name']) if top_dishes else None

    return render_template(
        "index.html",
        dishes=top_dishes,
        caption=caption,
        image_url=image_url,
        weather_info=weather_info,
        weather_caption=weather_caption,
        active_tab="sales",
        highlight_image=True,
        highlight_caption=False
    )


# === Handle POST: Publish Sales-Based Content to Instagram ===
@app.route("/post-to-instagram", methods=["POST"])
def post_to_instagram():
    image_url_relative = request.form.get("image_url")
    caption = request.form.get("caption")

    # Construct full absolute URL for the image
    if image_url_relative and not image_url_relative.startswith('http'):
        image_url = request.url_root.rstrip('/') + image_url_relative
    else:
        image_url = image_url_relative

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
    holiday_caption = request.form.get("holiday_caption")
    holiday_message = request.form.get("holiday_message")
    holiday_image_url = request.form.get("holiday_image_url")
    # 只刷新图片
    weather_image_url = get_image_from_caption(weather_caption)

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
        highlight_weather_image=True,
        active_tab="weather"
    )

# === Handle POST: Publish Weather-Based Content to Instagram ===
@app.route("/post-weather-to-instagram", methods=["POST"])
def post_weather_to_instagram():
    image_url_relative = request.form.get("weather_image_url")
    caption = request.form.get("weather_caption")

    # Construct full absolute URL for the image
    if image_url_relative and not image_url_relative.startswith('http'):
        image_url = request.url_root.rstrip('/') + image_url_relative
    else:
        image_url = image_url_relative

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
    weather_image_url = request.form.get("weather_image_url")
    holiday_caption = request.form.get("holiday_caption")
    holiday_message = request.form.get("holiday_message")
    # 只刷新节日图片
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
        weather_image_url=weather_image_url,
        holiday_caption=holiday_caption,
        holiday_message=holiday_message,
        holiday_image_url=holiday_image_url,
        highlight_holiday_image=True,
        active_tab="holiday"
    )



# === Handle POST: Publish Holiday-Based Content to Instagram ===
@app.route("/post-holiday-to-instagram", methods=["POST"])
def post_holiday_to_instagram():
    image_url_relative = request.form.get("holiday_image_url")
    caption = request.form.get("holiday_caption")

    # Construct full absolute URL for the image
    if image_url_relative and not image_url_relative.startswith('http'):
        image_url = request.url_root.rstrip('/') + image_url_relative
    else:
        image_url = image_url_relative

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
    weather_image_url = request.form.get("weather_image_url")
    holiday_message = request.form.get("holiday_message")
    holiday_image_url = request.form.get("holiday_image_url")
    # 清除自定义内容
    session.pop('edited_holiday_caption', None)
    holiday_info = get_holiday_info()
    if holiday_info["is_holiday"]:
        holiday_caption = generate_holiday_caption(holiday_info["message"], salt=str(uuid.uuid4()))
    else:
        holiday_caption = None
    session['edited_holiday_caption'] = holiday_caption  # 新增：同步 session
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
        highlight_holiday_caption=True,
        active_tab="holiday",
        editing_holiday_caption=False
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
    # 只刷新天气信息
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
    # 只刷新节日信息
    holiday_info = get_holiday_info()
    holiday_message = holiday_info["message"]
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
        holiday_image_url=holiday_image_url,
        active_tab="holiday"
    )

@app.route('/upload-images', methods=['GET', 'POST'])
def upload_images():
    if request.method == 'POST':
        files = request.files.getlist('images')
        dish_names = request.form.getlist('dish_names')
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
        # Load or initialize mapping
        if os.path.exists(DISH_IMAGE_MAP_PATH):
            with open(DISH_IMAGE_MAP_PATH, 'r') as f:
                dish_image_map = json.load(f)
        else:
            dish_image_map = {}
        for file, dish_name in zip(files, dish_names):
            if file and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f'{uuid.uuid4().hex}.{ext}'
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                dish_image_map.setdefault(dish_name, []).append(filename)
        # Save mapping
        with open(DISH_IMAGE_MAP_PATH, 'w') as f:
            json.dump(dish_image_map, f, indent=2)
        return '', 200
    return render_template('upload_images.html')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_dish_image(dish_name):
    try:
        with open('dish_image_map.json', 'r') as f:
            dish_image_map = json.load(f)
        if dish_name in dish_image_map and dish_image_map[dish_name]:
            filename = random.choice(dish_image_map[dish_name])  # Randomly select one image
            return f'/static/images/dishes/{filename}'
    except Exception as e:
        print(f"Error loading image for {dish_name}: {e}")
    return '/static/images/placeholder.jpg'

def get_image_from_caption(caption):
    """
    Parses a caption to find a dish name and returns a corresponding local image.
    """
    if not caption:
        return get_dish_image(None)
        
    try:
        with open(DISH_IMAGE_MAP_PATH, 'r') as f:
            dish_image_map = json.load(f)
        
        if not dish_image_map:
            # No dishes in the map, return placeholder
            return get_dish_image(None)

        # Search for any of the dish names in the caption (case-insensitive)
        for dish_name in dish_image_map.keys():
            if dish_name.lower() in caption.lower():
                print(f"✅ Found '{dish_name}' in weather caption, selecting a local image.")
                return get_dish_image(dish_name)

        # Fallback: if no dish is mentioned, pick a random image from the entire library
        print("🤔 No specific dish found in weather caption. Selecting a random local image as fallback.")
        random_dish = random.choice(list(dish_image_map.keys()))
        return get_dish_image(random_dish)

    except (FileNotFoundError, json.JSONDecodeError, IndexError):
        # Fallback in case of any error (e.g., file not found, empty map)
        return get_dish_image(None) # Returns the placeholder

@app.route('/manage-images', methods=['GET'])
def manage_images():
    # Load mapping
    try:
        with open(DISH_IMAGE_MAP_PATH, 'r') as f:
            dish_image_map = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dish_image_map = {}
    
    all_dish_names = sorted(list(dish_image_map.keys()))

    return render_template('manage_images.html', dish_image_map=dish_image_map, all_dish_names=all_dish_names, upload_folder=app.config['UPLOAD_FOLDER'])

@app.route('/delete-image', methods=['POST'])
def delete_image():
    filename = request.form['filename']
    dish_name = request.form['dish_name']
    # Remove file from disk
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    # Remove from mapping
    if os.path.exists(DISH_IMAGE_MAP_PATH):
        with open(DISH_IMAGE_MAP_PATH, 'r') as f:
            dish_image_map = json.load(f)
        if dish_name in dish_image_map and filename in dish_image_map[dish_name]:
            dish_image_map[dish_name].remove(filename)
            if not dish_image_map[dish_name]:
                del dish_image_map[dish_name]
        with open(DISH_IMAGE_MAP_PATH, 'w') as f:
            json.dump(dish_image_map, f, indent=2)
    return redirect(url_for('manage_images'))

@app.route('/replace-image', methods=['POST'])
def replace_image():
    old_filename = request.form['old_filename']
    dish_name = request.form['dish_name']
    new_file = request.files['new_image']
    # Save new file with the same filename (overwrite)
    if new_file and allowed_file(new_file.filename):
        file_path = os.path.join(UPLOAD_FOLDER, old_filename)
        new_file.save(file_path)
    return redirect(url_for('manage_images'))

@app.route('/change-image-category', methods=['POST'])
def change_image_category():
    filename = request.form['filename']
    old_dish_name = request.form['old_dish_name']
    new_dish_name = request.form['new_dish_name']
    # Update mapping
    if os.path.exists(DISH_IMAGE_MAP_PATH):
        with open(DISH_IMAGE_MAP_PATH, 'r') as f:
            dish_image_map = json.load(f)
        # Remove from old category
        if old_dish_name in dish_image_map and filename in dish_image_map[old_dish_name]:
            dish_image_map[old_dish_name].remove(filename)
            if not dish_image_map[old_dish_name]:
                del dish_image_map[old_dish_name]
        # Add to new category
        dish_image_map.setdefault(new_dish_name, []).append(filename)
        with open(DISH_IMAGE_MAP_PATH, 'w') as f:
            json.dump(dish_image_map, f, indent=2)
    return redirect(url_for('manage_images'))

# === Generate Instagram Caption Based on Holiday ===
@ttl_cache(ttl_seconds=86400)  # 缓存一天
def generate_holiday_caption(holiday_message, salt=None):
    prompt = f"Tomorrow is {holiday_message}. Write a festive Instagram caption recommending Vietnamese dishes."
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip() + "\n\n" + get_hashtags()
    except Exception as e:
        return f"⚠️ Error generating holiday caption: {str(e)}\n\n" + get_hashtags()

def get_hashtags():
    if not os.path.exists(SETTINGS_PATH):
        return "#vietspot #vietspotNYC #vietnamese #vietfood"
    with open(SETTINGS_PATH, "r") as f:
        data = json.load(f)
        return data.get("hashtags", "#vietspot #vietspotNYC #vietnamese #vietfood")

def set_hashtags(new_hashtags):
    with open(SETTINGS_PATH, "w") as f:
        json.dump({"hashtags": new_hashtags}, f, indent=2)

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        new_hashtags = request.form.get("hashtags", "").strip()
        set_hashtags(new_hashtags)
        flash("Hashtags updated successfully!", "success")
        return redirect(url_for("settings"))
    hashtags = get_hashtags()
    return render_template("settings.html", hashtags=hashtags)

if __name__ == "__main__":
    app.run(debug=True)