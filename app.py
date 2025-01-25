import os
import sqlite3

from secret_key import secret_key as default_key
from dotenv import load_dotenv

from flask import Flask, request, redirect, render_template, request, session
from flask_session import Session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables from .env file
load_dotenv()

# Configure application
app = Flask(__name__)

# Set the secret key
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", default_key)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Connect sqlite3 database
con = sqlite3.connect("dublbubl.db", check_same_thread=False)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    username TEXT NOT NULL,
    hash TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 1000
)
""")



@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
def index():
        return render_template('index.html')


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    username = request.form.get("username")
    password = request.form.get("password")
    confirmation = request.form.get("confirmation")

    if request.method == "POST":
        if not username:
            return "No username"
        elif not password:
            return "No password"
        elif not confirmation:
            return "No password confirmation"
        elif password != confirmation:
            return "Password confirmation does not match"
        
        # Check if the username already exists
        user = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user:
            return "username already exists"
        
        # Insert new user into users
        cur.execute("INSERT INTO users (username, hash) VALUES (?, ?)",
                    (username, generate_password_hash(password)))
        # Commit the changes to the database
        con.commit()

        # Fetch the new user's ID after inserting
        user = cur.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()

        # Log the user in by saving their id in the session
        session["user_id"] = user[0]

        # Redirect user to home page
        return redirect("/")
    
    else:
        return render_template("register.html")




@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    username = request.form.get("username")
    password = request.form.get("password")

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Check if username was entered
        if not username or not password:
            return "Username and password are required"

        # Check database for user details (username, hash, and id)
        user = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        # Check if username exists and password is correct
        if user is None or not check_password_hash(user[2], password):
            return "Invalid username and/or password"

        # Log the user in by saving their id in the session
        session["user_id"] = user[0]
        # Redirect user to home page
        return redirect("/")

    else:
        return render_template("login.html")
    
@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to home page
    return redirect("/")