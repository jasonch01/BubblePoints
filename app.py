import os
import psycopg2
import sqlite3
import datetime
import threading
import time
import re
import gevent
from gevent import monkey
monkey.patch_all()

# secret_key.py
# from secret_key import secret_key as default_key

from dotenv import load_dotenv

from flask import Flask, request, redirect, render_template, request, session, flash, url_for
from flask_socketio import SocketIO, emit, join_room
from flask_session import Session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables from .env file
load_dotenv()

# Configure application
app = Flask(__name__)

# Initialize Flask-SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")  # Allow all origins for local development

# Set the secret key
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")


# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Connect sqlite3 database
# con = sqlite3.connect("dublbubl.db", check_same_thread=False)
# cur = con.cursor()

# Connect to PostgreSQL database
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()




def init_db():
    # Create users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY NOT NULL,
        username TEXT NOT NULL UNIQUE,
        hash TEXT NOT NULL,
        points INTEGER NOT NULL DEFAULT 10000,
        total_points_earned INTEGER NOT NULL DEFAULT 0,
        email TEXT UNIQUE
    )
    """)

    # Create dublbubl table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dublbubl (
        row_id SERIAL PRIMARY KEY NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        points_in INTEGER NOT NULL,
        points_out INTEGER NOT NULL,
        date_created TEXT NOT NULL,        
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (username) REFERENCES users(username)
    )   
    """)

    # Create dublbubl history table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS dublbubl_history (
        history_id SERIAL PRIMARY KEY NOT NULL,
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
        tracker_id SERIAL PRIMARY KEY NOT NULL,
        current_points_in INTEGER NOT NULL,
        date_created TEXT NOT NULL        
    )   
    """)

init_db()

def is_valid_email(email):
    """Check if email is valid and case-insensitive."""
    # Convert email to lowercase for case-insensitive comparison
    email = email.lower()
    
    email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    
    return re.match(email_regex, email)

def is_valid_password(password):
    """Check if password meets security requirements."""
    if not password:
        return False

    # Regex for password validation
    # Ensure password is between 6 to 20 characters, with at least one lowercase letter, one uppercase letter, and one digit
    password_pattern = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z\d]{6,20}$"
    
    return bool(re.match(password_pattern, password))

def is_valid_username(username):
    """Check if the username meets the requirements."""
    # Convert username to lowercase for case-insensitive comparison
    username = username.lower()
    
    # Check if username length is between 3 and 20 characters
    if len(username) < 3 or len(username) > 20:
        return False, "Username must be between 3 and 20 characters long"
    
    # Check if username contains only letters and numbers
    if not re.match("^[a-zA-Z0-9]+$", username):
        return False, "Username can only contain letters and numbers"
    
    return True, ""


# Global flag to prevent multiple background tasks
timer_running = False

# Background countdown timer using socketio.start_background_task()
def countdown_timer():
    global timer_running  # Use the global flag to control the task state
    while True:
        # Open a new database connection to get the last row's timestamp
        thread_con = sqlite3.connect("dublbubl.db", check_same_thread=False)
        thread_cur = thread_con.cursor()

        last_row = thread_cur.execute("SELECT date_created FROM dublbubl ORDER BY row_id DESC LIMIT 1").fetchone()

        if last_row:
            last_timestamp = datetime.datetime.strptime(last_row[0], "%Y-%m-%d %H:%M:%S")
        else:
            last_timestamp = None

        # This will be the main loop where the timer will wait for a new row
        while last_timestamp:
            current_time = datetime.datetime.now()

            # Calculate the remaining time until 24 hours is reached
            remaining_time = 86400 - int((current_time - last_timestamp).total_seconds()) # 86400 seconds = 24 hours

            # If the remaining time is greater than 0, update the timer and sleep for 1 second
            if remaining_time > 0:
                hours, remainder = divmod(remaining_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                socketio.emit("update_timer", {"time": formatted_time})  # Emit the remaining time to frontend
                time.sleep(1)  # Sleep for 1 second before checking again
            else:
                # If 30 seconds have passed, perform the cleanup
                formatted_time = "00:00:00"  # Emit 00:00:00 when time runs out
                print("30 seconds elapsed with no new row. Clearing dublbubl table.")
                thread_cur.execute("DELETE FROM dublbubl")
                thread_con.commit()

                # Reset current_points_in to 0 in points_tracker table
                thread_cur.execute("UPDATE points_tracker SET current_points_in = 0")
                thread_con.commit()

                # Emit an empty table to the front-end
                socketio.emit("update_table", {"rows": []})  # Notify frontend of table reset

                # Emit the reset points to the frontend
                socketio.emit("update_points", {"current_points_in": 0})  # Notify frontend of points reset

                # Emit real-time update for current_points_in and points_in_required
                current_points_in = thread_cur.execute("SELECT current_points_in FROM points_tracker").fetchone()
                points_in_required = 0  # Default value 

                if current_points_in is None or points_in_required is None:
                    print("Error: current_points_in or points_in_required is None.")
                    points_in_required = 0  # Default value

                print(f"Emitting points info: {current_points_in[0]}, {points_in_required}")
                socketio.emit("update_points_info", {
                    "current_points_in": current_points_in[0],  # Emitting the actual points_in value
                    "points_in_required": points_in_required  # Emitting the calculated points_in_required
                })  # Broadcasts to all connected clients

                # Reset the timer_running flag to allow starting the timer again
                timer_running = False

                break  # Exit the loop and reset the process

            # Check if a new row has been added, and update the timestamp if necessary
            last_row = thread_cur.execute("SELECT date_created FROM dublbubl ORDER BY row_id DESC LIMIT 1").fetchone()
            if last_row:
                new_last_timestamp = datetime.datetime.strptime(last_row[0], "%Y-%m-%d %H:%M:%S")
                if new_last_timestamp > last_timestamp:
                    last_timestamp = new_last_timestamp
                    continue  # A new row has been added, restart the timer

        # Close the thread-specific connection
        thread_con.close()

        time.sleep(1)  # Sleep briefly before restarting the loop

# Start countdown timer using background task
def start_timer():
    global timer_running
    if not timer_running:
        socketio.start_background_task(target=countdown_timer)   # Start the countdown in the background
        timer_running = True # Set the flag to True, indicating the timer is running
        print("Countdown timer background task started.")
    else:
        print("Timer already running.")


@socketio.on('get_timer_state')
def get_timer_state():
    # Retrieve the current remaining time from the database or timer state
    thread_con = sqlite3.connect("dublbubl.db", check_same_thread=False)
    thread_cur = thread_con.cursor()

    last_row = thread_cur.execute("SELECT date_created FROM dublbubl ORDER BY row_id DESC LIMIT 1").fetchone()

    if last_row:
        last_timestamp = datetime.datetime.strptime(last_row[0], "%Y-%m-%d %H:%M:%S")
        current_time = datetime.datetime.now()
        remaining_time = 86400 - int((current_time - last_timestamp).total_seconds()) # 86400 seconds = 24 hours
        hours, remainder = divmod(remaining_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if remaining_time > 0 else "00:00:00"
    else:
        formatted_time = "00:00:00"  # Default if no rows exist

    # Emit the initial timer state to the front-end
    socketio.emit('initial_timer_state', {'time': formatted_time})





# Example Flask route to start the timer
@app.route("/start_timer")
def trigger_timer():
    start_timer()
    return "Timer started."


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

    updated_rows = []  # Initialize with an empty list

    # Start the timer when the user accesses the index
    start_timer()

    try:
        try:
            # Check database for dublbubl table
            dublbubl = cur.execute("SELECT * FROM dublbubl").fetchall()
        except Exception as e:
            print(f"Error executing query: {e}")

        # Get current page number from query parameters, default to 1
        page = request.args.get("page", 1, type=int)
        print(f"📢 Page received in request: {page}")  # Debugging output
        print(f"Request URL: {request.url}")
        print(f"Request Args: {request.args}")

        rows_per_page = 20  # Limit rows per page
        offset = (page - 1) * rows_per_page  # Calculate offset

         # Fetch limited rows based on pagination
        dublbubl = cur.execute(
            "SELECT * FROM dublbubl ORDER BY row_id ASC LIMIT ? OFFSET ?", 
            (rows_per_page, offset)
        ).fetchall()

        # Get total row count to calculate total pages
        total_rows = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]
        total_pages = (total_rows + rows_per_page - 1) // rows_per_page  # Round up



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
            user_history = cur.execute("SELECT * FROM dublbubl_history WHERE creator_id = ? ORDER BY row_id DESC LIMIT 5", (user_id,)).fetchall()
        else:
            user = None
            user_history = None

    except sqlite3.OperationalError as e:
        print("Error: dublbubl_history table does not exist, creating it.")
        init_db()

    # Handle None values for current_points_in and oldest_row_points_out
    if current_points_in is None or oldest_row_points_out is None:
        print("Error: current_points_in or oldest_row_points_out is None.")
        points_in_required = 0  # Default value
    else:
        # Perform the calculation only if both values are valid
        points_in_required = oldest_row_points_out[0] - current_points_in[0]
        


    # Emit real-time update for current_points_in and points_in_required
    socketio.emit("update_points_info", {
        "current_points_in": current_points_in[0],  # Emitting the actual points_in value
        "points_in_required": points_in_required  # Emitting the calculated points_in_required
    })  # Broadcasts to all connected clients

    points = request.form.get("points")
    current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = None
    
    if request.method == "POST":
        # Check if the user is logged in before allowing them to submit points
        if user_id is None:
            return render_template("login.html", message="You must be logged in to create a bubble")
        
        # Check points are entered
        if not points:
            flash("No points entered", "danger")  # Use "danger" for errors
            return redirect(url_for("index"))
        try:
            points = int(points)
        except ValueError:
            flash("Invalid input", "danger")
            return redirect(url_for("index"))

        # Check points are positive number
        if points is None:
            return "Invalid Input"
        elif points <= 0 or points > 10000:
            flash("Points must be between 1 and 10000", "danger")
            return redirect(url_for("index"))
    
    
    
         # Check database for user details
        user_id = session["user_id"]
        user = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

        # Fetch user's point balance
        current_points = cur.execute("SELECT points FROM users WHERE id = ?", (user[0],)).fetchone()
        current_points = current_points[0] if current_points else 0  # Default to 0 if no value exists
        
        # Ensure user has enough points     
        if current_points < points:
            flash("Not enough points", "danger")
            return redirect(url_for("index"))

        try:
            # Calculate the multiplier based on points_in
            if points >= 10000:
                points_out = points * 2  # If points are 10,000 or more, multiply by 2
            elif points >= 5000:
                points_out = points * 1.75  # If points are 5,000 or more but less than 10,000, multiply by 1.75
            elif points >= 1000:
                points_out = points * 1.5  # If points are 1,000 or more but less than 10,000, multiply by 1.5
            else:
                points_out = points * 1.25  # Otherwise, points_out equals points_in (e.g., for smaller amounts)

            # Insert row into dublbubl
            cur.execute("""
            INSERT INTO dublbubl (row_id, user_id, username, points_in, points_out, date_created)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (None, user[0], user[1], points, (points_out), current_date))

            # Commit the changes to the dublbubl database
            con.commit()

            # Fetch all updated rows to send to the front-end
            updated_rows = cur.execute("""
                SELECT * FROM dublbubl
                ORDER BY row_id ASC
            """).fetchall()

            # Get total row count to calculate total pages
            total_rows = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]

            page = request.form.get("page", 1, type=int)
            print(f"📢 Page received in post request: {page}")  # Debugging output
            print(f"Request URL: {request.url}")
            print(f"Request Args: {request.args}")
            
            # Calculate the total number of pages
            total_pages = (total_rows + rows_per_page - 1) // rows_per_page  # Round up

            # Calculate the OFFSET based on the current page
            offset = (page - 1) * rows_per_page

            # Debugging output
            print(f"Page: {page}, Rows per page: {rows_per_page}, Offset: {offset}")
            print(f"Fetching rows starting from: {offset}, Limit: {rows_per_page}")

            # Fetch rows for the current page using LIMIT and OFFSET
            updated_rows = cur.execute(
                "SELECT * FROM dublbubl ORDER BY date_created, row_id LIMIT ? OFFSET ?",
                (rows_per_page, offset)
            ).fetchall()

            # Emit the updated rows along with pagination details
            socketio.emit("update_table", {
                "rows": updated_rows,
                "total_pages": total_pages,
                "current_page": page
            })

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
            
        # Fetch current_points_in value
        current_points_in = cur.execute("SELECT current_points_in FROM points_tracker").fetchone()    


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
            # If there is one row, don't update points in points_tracker
            new_points_in = current_points_in[0] if current_points_in else 0
            print(f"New points in is { new_points_in }")


        oldest_row_points_out = cur.execute("SELECT points_out FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()
        
        # Print to debug
        print(f"Oldest row points out: {oldest_row_points_out[0]}")

        # Check if there are no rows or if points_out is None
        if oldest_row_points_out is None:
            print("No rows found in dublbubl. Exiting loop.")
        else:
            # If total points added exceed twice the oldest row's points, delete the oldest row
            while new_points_in >= oldest_row_points_out[0]:

                

                # Get the row ID of the oldest row
                oldest_row_id = cur.execute("SELECT row_id FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()
                oldest_row = cur.execute("SELECT * FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()



                # Ensure that oldest_row is not None before checking total points
                if oldest_row is not None:
                        # Fetch user's current total points
                        current_total_points = cur.execute("SELECT total_points_earned FROM users WHERE id = ?", (oldest_row[1],)).fetchone()

                        if current_total_points is None:
                            print("No points found for this user.")
                            current_total_points = 0  # Default to 0 if no value exists
                        else:
                            current_total_points = current_total_points[0]  # Extract the value from the tuple

                        print(f"Current total points: {current_total_points}")

                        # Fetch user's point balance only if oldest_row is not None
                        points = cur.execute("SELECT points FROM users WHERE id = ?", (oldest_row[1],)).fetchone()

                        if points is None:
                            print("No points balance found for this user.")
                            points = 0  # Default to 0 if no value exists
                        else:
                            points = points[0]  # Extract the value from the tuple

                        print(f"User's point balance: {points}")
                else:
                    print("Oldest row is None, skipping points check.")

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
                        WHERE creator_id = ?
                        ORDER BY row_id DESC 
                        LIMIT 5
                    """, (user[0],)).fetchall()

                    print(f"Checking user[0]: {user[0]}")

                    # Print the user_id and the fetched history to debug
                    print(f"Fetching history for creator_id: {user[0]}")
                    print("Fetched history:", updated_user_history)

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


                # Check if oldest_row_id is not None before attempting to delete the row
                if oldest_row_id is not None:
                    cur.execute("DELETE FROM dublbubl WHERE row_id = ?", (oldest_row_id[0],))
                    con.commit()
                else:
                    print("Error: oldest_row_id is None, unable to delete row.")

                # Calculate the remaining points in points_tracker
                remaining_points_in = new_points_in - oldest_row_points_out[0]

                # Update points_tracker with the remaining points
                cur.execute("UPDATE points_tracker SET current_points_in = ?, date_created = ?", (remaining_points_in, current_date))
                con.commit()

                # Fetch all updated rows to send to the front-end
                updated_rows = cur.execute("""
                    SELECT * FROM dublbubl
                    ORDER BY row_id ASC
                """).fetchall()


                # Get total row count to calculate total pages
                total_rows = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]

                page = request.form.get("page", 1, type=int)
                print(f"📢 Page received in post request: {page}")  # Debugging output
                print(f"Request URL: {request.url}")
                print(f"Request Args: {request.args}")

                # Calculate the total number of pages
                total_pages = (total_rows + rows_per_page - 1) // rows_per_page  # Round up

                # Calculate the OFFSET based on the current page
                offset = (page - 1) * rows_per_page

                # Debugging output
                print(f"Page: {page}, Rows per page: {rows_per_page}, Offset: {offset}")
                print(f"Fetching rows starting from: {offset}, Limit: {rows_per_page}")


                # Fetch rows for the current page using LIMIT and OFFSET
                updated_rows = cur.execute(
                    "SELECT * FROM dublbubl ORDER BY date_created, row_id LIMIT ? OFFSET ?",
                    (rows_per_page, offset)
                ).fetchall()

                # Emit the updated rows along with pagination details
                socketio.emit("update_table", {
                    "rows": updated_rows,
                    "total_pages": total_pages,
                    "current_page": page
                })

                # Ensure the update is triggered only after database changes
                print(f"Emitting updated rows to room: {user[0]}")

                new_points_in = remaining_points_in

                oldest_row_points_out = cur.execute("SELECT points_out FROM dublbubl ORDER BY row_id ASC LIMIT 1").fetchone()

                # Break the loop if there are no more rows in dublbubl
                if new_points_in <= 0 or oldest_row_points_out is None:
                    print("No more rows in dublbubl. Exiting loop.")
                    break

        try:
            points = request.form.get('points')

            if not points or not points.isdigit():
                flash("Invalid points value.", "danger")
                return redirect(request.url)  # Redirect back to the same page on error

            # Successfully created bubble
            flash("Bubble created successfully!", "success")

            # Get the current page from the form or query parameters
            current_page = request.form.get('page') or request.args.get('page', 1)  # Default to 1 if no page param
            
            # Convert current_page to an integer
            current_page = int(current_page)

            # Check if the current page exists (ensure that the page is within valid range)
            total_rows = cur.execute("SELECT COUNT(*) FROM dublbubl").fetchone()[0]
            rows_per_page = 20
            total_pages = (total_rows + rows_per_page - 1) // rows_per_page  # Calculate total pages

            # If the current page is greater than the total number of pages, set the page to the last valid page
            if current_page > total_pages:
                current_page = total_pages if total_pages > 0 else 1

            # Redirect back to the same page, including the page number
            return redirect(url_for('index', page=current_page))  # Redirect with 'page' query parameter

        except Exception as e:
            flash(f"An error occurred: {str(e)}", "danger")
            return redirect(request.url)  # In case of an error, you can fallback to the same page
        
    else:
        return render_template('index.html', dublbubl=dublbubl, user=user, message=message, current_points_in=current_points_in, points_in_required=points_in_required, user_history=user_history, updated_rows=updated_rows, total_pages=total_pages, current_page=page, page=page)


if __name__ == "__main__":
    try:
        start_timer()  # Start the countdown thread
        socketio.run(app, debug=True)
    except KeyboardInterrupt:
        print("Shutting down the server gracefully...")
        # Perform any cleanup here if needed


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        # Check username conditions
        if not username:
            return render_template("register.html", message="Username required")
        # Check username validity
        is_valid, username_message = is_valid_username(username)
        if not is_valid:
            return render_template("register.html", message=username_message)

        # Check email conditions
        if not email:
            return render_template("register.html", message="Email Address required")
        if not is_valid_email(email):
            return render_template("register.html", message="Invalid email format")

        # Check password conditions
        if not password:
            return render_template("register.html", message="Password required")
        if not confirmation:
            return render_template("register.html", message="Password confirmation required")
        if password != confirmation:
            return render_template("register.html", message="Password confirmation does not match")
        if not is_valid_password(password):
            return render_template("register.html", message="Password must be between 6 to 20 characters, with at least one lowercase letter, one uppercase letter, and one digit")

        # Check if the username already exists
        user = cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
        if user:
            return render_template("register.html", message="Username already exists")

        # Check if the email already exists
        user_email = cur.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,)).fetchone()
        if user_email:
            return render_template("register.html", message="Email already exists")

        # Insert new user if all checks pass
        cur.execute("INSERT INTO users (username, email, hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)))
        con.commit()

        # Fetch new user ID
        user = cur.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        session["user_id"] = user[0]

        return redirect("/")

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
            return render_template("login.html", message="Username and password are required")

        # Check database for user details (username, hash, and id)
        user = cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()

        # Check if username exists and password is correct
        if user is None or not check_password_hash(user[2], password):
            return render_template("login.html", message="Invalid username and/or password")

        # Log the user in by saving their id in the session
        session["user_id"] = user[0]
        # Redirect user to index
        return redirect("/")

    else:
        return render_template("login.html")
    
@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to index
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
    
    
@app.route("/history", methods=["GET", "POST"])
def history():
    """History"""

    dublbubl_history = cur.execute("SELECT row_id, creator_username, points_in, points_out, date_created FROM dublbubl_history users ORDER BY row_id DESC LIMIT 50").fetchall()

    if request.method == "POST":
        return redirect("/")
    
    else:
        return render_template("history.html", dublbubl_history=dublbubl_history)
    

@app.route("/account", methods=["GET", "POST"])
@login_required
def change_password():
    """Change user password"""
    if request.method == "POST":
        
        password = request.form.get("password")
        new_password = request.form.get("new_password")
        confirmation = request.form.get("confirmation")

        # Check password conditions
        if not password:
            return render_template("account.html", message="Password required")
        if not new_password:
            return render_template("account.html", message="New password required")
        if not confirmation:
            return render_template("account.html", message="New password confirmation required")
        if new_password != confirmation:
            return render_template("account.html", message="Password confirmation does not match")
        if not is_valid_password(new_password):
            return render_template("account.html", message="New password must be between 6 to 20 characters, with at least one lowercase letter, one uppercase letter, and one digit")

        # Check database for user details
        user_id = session["user_id"]
        user = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        print(user)
        print(user_id)
 

        # Check if the username already exists
        if not user:
            return render_template("account.html", message="User not found")

        # Get the stored hashed password
        stored_password_hash = user[2]

        # Check if the entered password matches the stored hash
        if not check_password_hash(stored_password_hash, password):
            return render_template("account.html", message="Invalid current password")
        
        # Check if the current password is the same as the new password
        if password == new_password:
            return render_template("account.html", message="New password cannot be the same as the current password")

        # If password is correct, proceed to change it
        hashed_new_password = generate_password_hash(new_password)
        
        # Update the password in the database
        cur.execute("UPDATE users SET hash = ? WHERE id = ?", (hashed_new_password, user_id))
        con.commit()

        return render_template("account.html", message="Password changed successfully")

    return render_template("account.html")