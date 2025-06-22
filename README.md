# Restaurant AI Assistant 2.0

This is a Flask web application designed to help restaurant owners automate their social media marketing. It fetches top-selling dishes from Square, gets current weather data, and checks for upcoming holidays to generate relevant promotional content using OpenAI's GPT-4 and DALL-E 3.

## How to Run the Project

This project can be run using either Poetry or Python's standard `pip` and `venv`.

### Method 1: Using Poetry (Recommended if you have it)

### 1. Prerequisites

*   **Python 3.11+**
*   **Poetry**: This project uses Poetry for dependency management. If you don't have it, you can install it by following the official instructions: [https://python-poetry.org/docs/#installation](https://python-poetry.org/docs/#installation)

### 2. Install Dependencies

Once you have Poetry installed, navigate to the project's root directory in your terminal and run:

```bash
poetry install
```

This will create a virtual environment and install all the necessary Python packages.

### 3. Set Up Environment Variables

The application requires API keys from several services to function correctly. You need to create a file named `.env` in the root of the project directory.

1.  Create the file:
    ```bash
    touch .env
    ```
2.  Open the `.env` file and add the following lines, replacing the placeholder values with your actual API keys:

    ```
    # OpenAI API Key (for generating text and images)
    OPENAI_API_KEY="YOUR_OPENAI_API_KEY"

    # Square API Credentials (for fetching sales data)
    SQUARE_ACCESS_TOKEN="YOUR_SQUARE_ACCESS_TOKEN"
    SQUARE_LOCATION_ID="YOUR_SQUARE_LOCATION_ID"

    # OpenWeatherMap API Key (for weather data)
    WEATHER_API_KEY="YOUR_OPENWEATHERMAP_API_KEY"

    # Calendarific API Key (for holiday data)
    HOLIDAY_API_KEY="YOUR_CALENDARIFIC_API_KEY"
    ```

### 4. Run the Application

After installing the dependencies and setting up your environment variables, you can run the Flask development server with this command:

```bash
poetry run flask --app main run
```

You should see output indicating that the server is running. You can then access the application by opening your web browser and navigating to the URL provided (usually `http://127.0.0.1:5000`).

### Method 2: Using Pip and Venv (If you don't have Poetry)

If you prefer not to install Poetry, you can use Python's built-in package manager, `pip`.

#### 1. Create and Activate a Virtual Environment

It's a good practice to create a virtual environment to keep project dependencies isolated.

```bash
# Create a virtual environment named 'venv'
python3 -m venv venv

# Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate
```
You'll know it's active when you see `(venv)` at the beginning of your terminal prompt.

#### 2. Install Dependencies with Pip

Run the following command to install the necessary packages:

```bash
pip install flask gunicorn openai requests python-dotenv
```

#### 3. Set Up Environment Variables

This step is the same as in the Poetry method. Create a `.env` file in the project root and add your API keys.

```
OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
SQUARE_ACCESS_TOKEN="YOUR_SQUARE_ACCESS_TOKEN"
SQUARE_LOCATION_ID="YOUR_SQUARE_LOCATION_ID"
WEATHER_API_KEY="YOUR_OPENWEATHERMAP_API_KEY"
HOLIDAY_API_KEY="YOUR_CALENDARIFIC_API_KEY"
```

#### 4. Run the Application

With the virtual environment activated, run the Flask development server:

```bash
flask --app main run
```

Access the application at `http://127.0.0.1:5000`.

## Project Structure

*   `main.py`: The main Flask application file containing all the routes and logic.
*   `templates/`: Contains the HTML templates for the web interface.
*   `static/`: Contains static assets like CSS, JavaScript, and images.
*   `pyproject.toml`: Defines project dependencies for Poetry.
*   `dish_image_map.json`: A file that maps dish names to specific image files.
*   `.env`: (You need to create this) Stores your secret API keys. 