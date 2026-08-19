message = "I want you to access the process logs directly for batch batch_dd1074ab and regenerate the previous document"
message_lower = message.lower()
print(f"message_lower: {message_lower}")
print(f"contains last: {'last' in message_lower}")
print(f"contains latest: {'latest' in message_lower}")
print(f"contains previous: {'previous' in message_lower}")
print(f"contains log: {'log' in message_lower}")
print(f"contains logs: {'logs' in message_lower}")

keywords = ["regenerate", "re-generate", "recreate", "re-create", "previous document"]
for k in keywords:
    print(f"contains '{k}': {k in message_lower}")

any_val = any(k in message_lower for k in keywords)
print(f"any: {any_val}")

is_last_cleaned_logs = (
    ("last" in message_lower or "latest" in message_lower or "previous" in message_lower)
    and ("log" in message_lower or "logs" in message_lower)
    and not any_val
)
print(f"is_last_cleaned_logs: {is_last_cleaned_logs}")
