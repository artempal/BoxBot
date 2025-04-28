"""Fuzzy search utilities for BoxBot."""

import Levenshtein
from typing import List, TypeVar, Callable

T = TypeVar('T')

def fuzzy_search(query: str, items: List[T], 
                get_text: Callable[[T], str], 
                threshold: float = 0.7) -> List[T]:
    """
    Perform fuzzy search on a list of items.
    
    Args:
        query: The search query
        items: List of items to search through
        get_text: Function to extract text from each item for comparison
        threshold: Similarity threshold (0-1, higher is more strict)
        
    Returns:
        List of matching items sorted by similarity (most similar first)
    """
    results = []
    query_lower = query.lower()
    
    for item in items:
        item_text = get_text(item).lower()
        
        # First check if the query is a substring (exact match)
        if query_lower in item_text:
            # Add with a high score to prioritize exact matches
            results.append((item, 1.0))
            continue
            
        # Calculate Levenshtein ratio for fuzzy matching
        ratio = Levenshtein.ratio(query_lower, item_text)
        
        if ratio >= threshold:
            results.append((item, ratio))
    
    # Sort by similarity ratio (descending)
    results.sort(key=lambda x: x[1], reverse=True)
    
    # Return just the items
    return [item for item, _ in results] 