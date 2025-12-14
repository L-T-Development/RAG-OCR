import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


def embedding_similarity(model, text1, text2):
    emb1 = model.encode([text1])
    emb2 = model.encode([text2])
    return cosine_similarity(emb1, emb2)[0][0]


def answer_relevance(model, question, answer, threshold=0.35):
    score = embedding_similarity(model, question, answer)
    return score, score >= threshold


def context_precision(model, question, chunks, threshold=0.35):
    if not chunks:
        return 0.0

    relevant = 0
    for chunk in chunks:
        sim = embedding_similarity(model, question, chunk)
        if sim >= threshold:
            relevant += 1

    return relevant / len(chunks)


def faithfulness(answer, chunks, model, threshold=0.35):
    if not chunks or not answer.strip():
        return 0.0

    answer_emb = model.encode([answer])

    supported = 0
    for chunk in chunks:
        chunk_emb = model.encode([chunk])
        sim = cosine_similarity(answer_emb, chunk_emb)[0][0]
        if sim >= threshold:
            supported += 1

    return supported / len(chunks)



def context_recall(answer, chunks):
    answer_sentences = [s.strip() for s in answer.split('.') if len(s.strip()) > 20]

    if not answer_sentences:
        return 0.0

    covered = 0
    for sent in answer_sentences:
        if any(sent.lower() in chunk.lower() for chunk in chunks):
            covered += 1

    return covered / len(answer_sentences)
