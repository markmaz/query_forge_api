USE workboard_new;

CREATE TABLE zip_code (
  zip CHAR(5) NOT NULL,
  state_id CHAR(2) NOT NULL,
  PRIMARY KEY (zip),
  KEY ix_zip_state (state_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;