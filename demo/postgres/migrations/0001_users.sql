-- Users of the demo shop.
CREATE TABLE users (
    id         integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email      text NOT NULL UNIQUE,
    full_name  text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE users IS 'Application users';
CREATE INDEX users_created_at_idx ON users (created_at);
