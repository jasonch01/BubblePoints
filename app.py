import os
import sqlite3
import datetime

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


def init_db():
    # Create users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        username TEXT NOT NULL,
        hash TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 1000
    )
    """)

    # Create dublbubl table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dublbubl (
        row_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        points_in INTEGER NOT NULL,
        points_out INTEGER NOT NULL,
        date_created TEXT NOT NULL,        
        FOREIGN KEY (user_id) REFERENCES users(id)
        FOREIGN KEY (username) REFERENCES users(username)
    )   
    """)

    # Create points_tracker table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS points_tracker (
        tracker_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        current_points_in INTEGER NOT NULL,
        date_created TEXT NOT NULL        
    )   
    """)

init_db()

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


@app.route("/", methods=["GET", "POST"])
def index():

    # Check database for dublbubl table
    dublbubl = cur.execute("SELECT * FROM dublbubl").fetchall()

    current_points_in = cur.execute("SELECT current_points_in FROM points_tracker").fetchone()
    print(f"Current points in points tracker: {current_points_in[0]}")   

    points = request.form.get("points")
    current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if request.method == "POST":
        # Check points are entered
        if not points:
            return "No points entered"
        try:
            points = int(points)
        except ValueError:
            return "Invalid Input"

        # Check points are positive number
        if points is None:
            return "Invalid Input"
        elif points <= 0:
            return "Points must be postiive"
    
        
         # Check database for user details
        user_id = session["user_id"]
        user = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

        try:
            # Insert row into dublbubl
            cur.execute("""
            INSERT INTO dublbubl (row_id, user_id, username, points_in, points_out, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (None, user[0], user[1], points, (points * 2), current_date))
            # Commit the changes to the dublbubl database
            con.commit()
        except Exception as e:
            print(f"Error inserting row into dublbubl: {e}")
            con.rollback()

        # Fetch the number of rows in dublbubl
        row_count = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]
        print(f"Number of rows in dublbubl: {row_count}")


        # Add points_in to points_tracker only if dublbubl has more than 1 row
        if row_count > 1:
            if current_points_in:
                new_points_in = current_points_in[0] + points
                cur.execute("UPDATE points_tracker SET current_points_in = ?, date_created = ?", (new_points_in, current_date))
            else:
                cur.execute("INSERT INTO points_tracker (current_points_in, date_created) VALUES (?, ?)", (points, current_date))

            # Commit the changes to the points_tracker database   
            con.commit()
        else:
            # If there is only one row, don't update points in points_tracker
            new_points_in = current_points_in[0] if current_points_in else 0

        oldest_row_points_out = cur.execute("SELECT points_out FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()
        
        print(f"Current_points_in: {current_points_in[0]}")

        # If total points added exceed twice the oldest row's points, delete the oldest row
        while new_points_in >= oldest_row_points_out[0]:
            print(f"Oldest row points_out: {oldest_row_points_out[0]}")

            # Get the row ID of the oldest row
            oldest_row_id = cur.execute("SELECT row_id FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()

            print(f"Current points before deletion: {current_points_in[0]}")

            #Delete the oldest row
            cur.execute("DELETE FROM dublbubl WHERE row_id = ?", (oldest_row_id[0],))
            con.commit()

            print(f"Deleting row with points_out: {oldest_row_points_out[0]}")

            # Calculate the remaining points in points_tracker
            remaining_points_in = new_points_in - oldest_row_points_out[0]

            # Update points_tracker with the remaining points
            cur.execute("UPDATE points_tracker SET current_points_in = ?, date_created = ?", (remaining_points_in, current_date))
            con.commit()

            new_points_in = remaining_points_in

            oldest_row_points_out = cur.execute("SELECT points_out FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()

            if oldest_row_points_out is None:
                break


        return redirect("/")
        
    else:
        return render_template('index.html', dublbubl=dublbubl)








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