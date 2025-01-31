import os
import sqlite3
import datetime

from secret_key import secret_key as default_key
from dotenv import load_dotenv

from flask import Flask, request, redirect, render_template, request, session
from flask_socketio import SocketIO, emit, join_room
from flask_session import Session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables from .env file
load_dotenv()

# Configure application
app = Flask(__name__)

# Initialize Flask-SocketIO
socketio = SocketIO(app)


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
        points INTEGER NOT NULL DEFAULT 1000,
        total_points_earned INTEGER NOT NULL DEFAULT 0
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

    # Create dublbubl history table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dublbubl_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,       
        row_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        creator_username TEXT NOT NULL,
        points_in INTEGER NOT NULL,
        points_out INTEGER NOT NULL,
        date_created TEXT NOT NULL,
        date_archived TEXT NOT NULL
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


@socketio.on('connect')
def on_connect():
    user_id = session.get("user_id")  # Ensure user_id is available
    if user_id:
        # Join the room based on the user's ID
        join_room(user_id)
        print(f"User {user_id} joined room")



@app.route("/", methods=["GET", "POST"])
def index():
    try:
        # Check database for dublbubl table
        dublbubl = cur.execute("SELECT * FROM dublbubl").fetchall()

        # Define the number of rows per page
        rows_per_page = 20

        # Get the current page number from the query string (default is page 1)
        page = request.args.get("page", 1, type=int)

        # Calculate the offset based on the current page
        offset = (page - 1) * rows_per_page

        # Fetch the rows for the current page
        dublbubl = cur.execute("""
            SELECT * FROM dublbubl
            ORDER BY row_id ASC
            LIMIT ? OFFSET ?
        """, (rows_per_page, offset)).fetchall()

        # Get the total number of rows in the dublbubl table for pagination
        total_rows = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]

        # Calculate the total number of pages
        total_pages = (total_rows + rows_per_page - 1) // rows_per_page

        # Fetch current points_in from points_tracker
        current_points_in = cur.execute("SELECT current_points_in FROM points_tracker").fetchone()

        # Fetch the oldest row's points_out
        oldest_row_points_out = cur.execute("SELECT points_out FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()

    

        # Check if user is logged in
        user_id = session.get("user_id")

        # Fetch the necessary data (e.g., user details) for logged-in users
        if user_id:
            # Fetch the user details
            user = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchall()
            # Fetch the last 5 user's dublbubl history
            user_history = cur.execute("SELECT * FROM dublbubl_history WHERE user_id = ? ORDER BY row_id DESC LIMIT 5", (user_id,)).fetchall()
        else:
            user = None
            user_history = None

    except sqlite3.OperationalError as e:
        print("Error: dublbubl_history table does not exist, creating it.")
        init_db()

    # Initialize points_in_required
    points_in_required = oldest_row_points_out[0] - current_points_in[0]


    points = request.form.get("points")
    current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if request.method == "POST":
        # Check if the user is logged in before allowing them to submit points
        if user_id is None:
            return "You must be logged in to submit points."
        
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
        elif points <= 0 or points > 10000:
            return "Points must be between 1 and 10000"
    
        
         # Check database for user details
        user_id = session["user_id"]
        user = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

        # Fetch user's point balance
        current_points = cur.execute("SELECT points FROM users WHERE id = ?", (user[0],)).fetchone()
        current_points = current_points[0] if current_points else 0  # Default to 0 if no value exists
        
        # Ensure user has enough points     
        if current_points < points:
            return "not enough points"

        try:
            # Insert row into dublbubl
            cur.execute("""
            INSERT INTO dublbubl (row_id, user_id, username, points_in, points_out, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (None, user[0], user[1], points, (points * 2), current_date))

            # Deduct from total points and update it in the database
            total_points = current_points - points

            # Check total points is not negative
            if total_points < 0:
                return "Error: Insufficient points balance."

            cur.execute("UPDATE users SET points = ? WHERE id = ?", (total_points, user[0]))
            # Commit the changes to the dublbubl database
            con.commit()

            # Emit an event to update the user's points balance in real-time (only the point_balance)
            socketio.emit("update_point_balance", {
                "point_balance": total_points  # Emitting only the total points balance
            }, room=user[0])  # Emits only to the specific user
            print(f"Emitting update to room: {user[0]} with new balance: {total_points}")


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

        

        # If total points added exceed twice the oldest row's points, delete the oldest row
        while new_points_in >= oldest_row_points_out[0]:

            # Get the row ID of the oldest row
            oldest_row_id = cur.execute("SELECT row_id FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()
            oldest_row = cur.execute("SELECT * FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()

            # Fetch user's current total points
            current_total_points = cur.execute("SELECT total_points_earned FROM users WHERE id = ?", (oldest_row[1],)).fetchone()
            current_total_points = current_total_points[0] if current_total_points else 0  # Default to 0 if no value exists

            # Fetch user's point balance
            points = cur.execute("SELECT points FROM users WHERE id = ?", (oldest_row[1],)).fetchone()
            points = points[0] if points else 0  # Default to 0 if no value exists

            #Insert the oldest row into dublbubl_history
            if oldest_row:
                cur.execute("""
                INSERT INTO dublbubl_history (user_id, username, row_id, creator_id, creator_username, points_in, points_out, date_created, date_archived)
                VALUES (?, ? ,?, ?, ? ,?, ?, ?, ?)
                """, (user[0], user[1], oldest_row[0], oldest_row[1], oldest_row[2], oldest_row[3], oldest_row[4], oldest_row[5], current_date))
                con.commit()

                # Fetch the latest 5 history records from all users
                updated_user_history = cur.execute("""
                    SELECT * FROM dublbubl_history 
                    ORDER BY row_id DESC LIMIT 5
                """).fetchall()

                # Emit an event to update the user's history in real-time
                socketio.emit("update_user_history", {
                    "history": [
                        {
                            "bubble_number": row[3], 
                            "points_invested": row[6], 
                            "points_earned": row[7], 
                            "created_on": row[8], 
                            "archived_on": row[9]
                        } for row in updated_user_history
                    ]
                }, room=user[0])  # Emits only to the specific user
                print(f"Emitting update to room: {user[0]} with updated user history: {oldest_row[4]}")



                # Add total_points_earned and update it in the database
                total_points_earned = current_total_points + oldest_row[4]
                cur.execute("UPDATE users SET total_points_earned = ? WHERE id = ?", (total_points_earned, oldest_row[1]))
                con.commit()

                # Add total points and update it in the database
                total_points = points + oldest_row[4]
                cur.execute("UPDATE users SET points = ? WHERE id = ?", (total_points, oldest_row[1]))
                con.commit() 
  
                # Update current_total_points to reflect new total
                current_total_points = total_points_earned

                updated_total_points = cur.execute("SELECT points FROM users WHERE id = ?",(user_id,)).fetchone()
                updated_total_points = updated_total_points[0] if updated_total_points else 0

                # Emit an event to update the user's points balance in real-time
                socketio.emit("update_point_balance", {
                    "point_balance": updated_total_points  # Only emitting the total points balance
                }, room=user_id)  # Emits only to the specific user
                print(f"Emitting update to room: {user_id} with new balance: {updated_total_points}")


            #Delete the oldest row from dublbubl    
            cur.execute("DELETE FROM dublbubl WHERE row_id = ?", (oldest_row_id[0],))
            con.commit()

            # Calculate the remaining points in points_tracker
            remaining_points_in = new_points_in - oldest_row_points_out[0]

            # Update points_tracker with the remaining points
            cur.execute("UPDATE points_tracker SET current_points_in = ?, date_created = ?", (remaining_points_in, current_date))
            con.commit()


            # Fetch the updated rows to send to the front-end
            updated_rows = cur.execute("""
                SELECT * FROM dublbubl
                ORDER BY row_id ASC
                LIMIT ? OFFSET ?
            """, (rows_per_page, offset)).fetchall()

            # Emit the updated rows to all connected clients
            socketio.emit("update_table", {"rows": updated_rows, "page": page})

            new_points_in = remaining_points_in

            # Break the loop if there are no more rows in dublbubl
            if row_count == 0 or new_points_in <= 0:
                break
        
        return redirect("/")
        
    else:
        return render_template('index.html', dublbubl=dublbubl, user=user, current_points_in=current_points_in, points_in_required=points_in_required, user_history=user_history, page=page, total_pages=total_pages)


if __name__ == "__main__":
    socketio.run(app, debug=True)



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


@app.route("/leaderboard", methods=["GET", "POST"])
def leaderboard():
    """Leaderboard"""

    user = cur.execute("SELECT username, total_points_earned FROM users ORDER BY total_points_earned DESC LIMIT 5").fetchall()

    print(user[0][0])

    if request.method == "POST":
        return redirect("/")
    
    else:
        return render_template("leaderboard.html", user=user)