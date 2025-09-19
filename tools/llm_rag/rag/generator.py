def generate_answer(question: str, contexts: list):
    if not contexts:
        return "No enough proofs"
    joined = "\n---\n".join(contexts[:3])
    return f"Q: {question}\nA(based on):\n{joined}"
