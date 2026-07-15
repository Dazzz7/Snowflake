def record_feedback(session_id: str, rating: str, note: str | None = None) -> dict:
    return {"session_id": session_id, "rating": rating, "recorded": True, "note": note}

