def clean_gemini_response(text):
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if line == "M4A":
            continue

        if line.startswith("+ ") and line[2:].isdigit():
            continue

        if line == "":
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue

        cleaned.append(line)

    return "\n".join(cleaned).strip()
