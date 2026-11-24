-- Who may touch the tables.
GRANT SELECT ON users, orders TO app_readonly;
GRANT SELECT, INSERT, UPDATE ON orders TO app_writer;
