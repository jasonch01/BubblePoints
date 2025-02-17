BEGIN;

-- Create users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,  -- Use SERIAL for auto-incrementing
    username TEXT NOT NULL UNIQUE,  -- Make username unique
    hash TEXT NOT NULL,
    points NUMERIC NOT NULL DEFAULT 1000,  -- Use NUMERIC for precise values
    total_points_earned NUMERIC NOT NULL DEFAULT 0,  -- Use NUMERIC for precise values
    email TEXT UNIQUE
);

-- Create dublbubl table
CREATE TABLE dublbubl (
    row_id SERIAL PRIMARY KEY,  -- Use SERIAL for auto-incrementing integer (PostgreSQL equivalent of AUTOINCREMENT)
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    points_in INTEGER NOT NULL,
    points_out INTEGER NOT NULL,
    date_created TIMESTAMP NOT NULL,  -- Use TIMESTAMP for date storage
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_username FOREIGN KEY (username) REFERENCES users(username)
);

-- Create points_tracker table
CREATE TABLE points_tracker (
    tracker_id SERIAL PRIMARY KEY,  -- Use SERIAL for auto-incrementing
    current_points_in INTEGER NOT NULL,
    date_created TIMESTAMP NOT NULL  -- Use TIMESTAMP for date storage
);

-- Create dublbubl_history table
CREATE TABLE dublbubl_history (
    history_id SERIAL PRIMARY KEY,  -- Use SERIAL for auto-incrementing
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    creator_id INTEGER NOT NULL,
    creator_username TEXT NOT NULL,
    points_in INTEGER NOT NULL,
    points_out INTEGER NOT NULL,
    date_created TIMESTAMP NOT NULL,
    date_archived TIMESTAMP NOT NULL  -- Use TIMESTAMP for date storage
);


-- Insert sample data into users table
INSERT INTO users (id, username, hash, points, total_points_earned, email)
VALUES
    (1, 'Jason', 'scrypt:32768:8:1$DZvrsoL4CpfWlEkL$1c2fcc802dd8b0d335438cf1cc2a253d05e89ff056807f4ff787e9244c0753ef7ffadc96419604e3d31a689df0983d5d5b4e451cc7b25f30a2cb93ff08c8ad9e', 594908.5, 507342.5, 'jasonch91@gmail.com'),
    (4, 'John', 'scrypt:32768:8:1$HmHACrW8GN94cVcg$2ac35f26173d7139dab2823ffca7c418d839ca6cbc396121094e43f731b0c0df23e162ea82ce2b71265cfbe4ecaab2c89ef44ad155213b1a6998758b04eadbde', 33, 1435, 'john.doe@example.com'),
    (8, 'Brian', 'scrypt:32768:8:1$heONyDxWseYhgw8X$5d93680f2b8e87d02b8ac7714481b85e231906a147d8a9f2923e60d4e86c3d96df2af42a89315c8008ffe8896c92fb837daa180a146cda50021ba248d5c99cb1', 800, 0, 'brian@example.com');

-- No need for INSERT INTO sqlite_sequence as it's specific to SQLite

COMMIT;
