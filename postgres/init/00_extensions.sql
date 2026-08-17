-- Runs once on a fresh pgdata volume. For existing installs, the backend
-- issues CREATE EXTENSION IF NOT EXISTS on first use, so this file is
-- belt-and-braces, not load-bearing.
CREATE EXTENSION IF NOT EXISTS hypopg;
