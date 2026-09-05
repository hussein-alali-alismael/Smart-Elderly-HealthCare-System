-- Store only one-way password hashes, never plaintext passwords.
ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL AFTER email;