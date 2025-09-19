def split_text(text: str, chunk_size=500, overlap=50):
    chunks, n, i = [], len(text), 0
    while i < n:
        j = min(i + chunk_size, n)
        chunks.append(text[i:j])
        i = j - overlap if j - overlap > i else j
    return chunks
