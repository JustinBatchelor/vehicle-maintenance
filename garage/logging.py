import json
import logging
class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"level": record.levelname, "logger": record.name, "message": record.getMessage(), "time": self.formatTime(record)})
