CREATE TABLE events (
    id INT PRIMARY KEY IDENTITY,
    title NVARCHAR(255),
    start_time DATETIME,
    end_time DATETIME,
    description NVARCHAR(MAX)
);