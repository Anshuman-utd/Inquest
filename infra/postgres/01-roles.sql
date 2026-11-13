-- Development-only credentials. Hosted roles are provisioned with managed secrets.
CREATE ROLE inquest_migrator LOGIN PASSWORD 'local_migrator';
CREATE ROLE inquest_api LOGIN PASSWORD 'local_api';
CREATE ROLE inquest_tool LOGIN PASSWORD 'local_tool';
CREATE ROLE inquest_eval LOGIN PASSWORD 'local_eval';

ALTER DATABASE inquest OWNER TO inquest_migrator;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
