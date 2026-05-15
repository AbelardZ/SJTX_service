from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

def extract_features(texts, method='tfidf'):
    """
    Extract features from a list of texts using the specified method.

    Parameters:
    texts (list of str): The input texts to extract features from.
    method (str): The feature extraction method to use ('count' or 'tfidf').

    Returns:
    array: The extracted feature matrix.
    """
    if method == 'count':
        vectorizer = CountVectorizer()
    elif method == 'tfidf':
        vectorizer = TfidfVectorizer()
    else:
        raise ValueError("Method must be 'count' or 'tfidf'.")

    feature_matrix = vectorizer.fit_transform(texts)
    return feature_matrix

def extract_keywords(text, top_n=5):
    """
    Extract keywords from a single text using TF-IDF.

    Parameters:
    text (str): The input text to extract keywords from.
    top_n (int): The number of top keywords to return.

    Returns:
    list: A list of top keywords.
    """
    vectorizer = TfidfVectorizer()
    X = vectorizer.fit_transform([text])
    feature_array = X.toarray()
    tfidf_sorting = feature_array[0].argsort()[::-1]

    feature_names = vectorizer.get_feature_names_out()
    top_keywords = [feature_names[i] for i in tfidf_sorting[:top_n]]
    return top_keywords