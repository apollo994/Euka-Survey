#!/usr/bin/env python3
"""
Functions for querying the SQLite database of precomputed features.
"""

import sqlite3


def build_phylum_metadata(conn, taxids, exclude_empty=False):
    """
    In-memory replacement for phylo_divbarchart.load_data().
    Uses bulk queries to fetch all required metadata at database speeds.
    """
    phylum_metadata = {}
    
    if not taxids:
        return phylum_metadata
        
    cursor = conn.cursor()
    chunk_size = 900 # Safe under SQLite 999 variable limits
    
    for i in range(0, len(taxids), chunk_size):
        chunk = taxids[i:i + chunk_size]
        placeholders = ','.join(['?'] * len(chunk))
        
        cursor.execute(f"""
            SELECT taxid, n_rows, c_ass, c_ann, c_rna, c_lng, s_ass, s_ann, s_rna, s_lng 
            FROM precomputed_clade_features 
            WHERE taxid IN ({placeholders})
        """, chunk)
        
        results = {row[0]: row[1:] for row in cursor.fetchall()}
        
        for taxid in chunk:
            row = results.get(int(taxid))
            
            if not row:
                if exclude_empty:
                    continue
                phylum_metadata[taxid] = {
                    'n_rows': 0, 'c_ass': 0, 'c_ann': 0, 'c_rna': 0, 'c_lng': 0,
                    's_ass': 0, 's_ann': 0, 's_rna': 0, 's_lng': 0,
                    'p_ass': 0.0, 'p_ann': 0.0, 'p_rna': 0.0, 'p_lng': 0.0
                }
                continue
                
            n = row[0]
            c_ass, c_ann, c_rna, c_lng = row[1], row[2], row[3], row[4]
            s_ass, s_ann, s_rna, s_lng = row[5], row[6], row[7], row[8]
            
            if exclude_empty and c_ass == 0 and c_ann == 0 and c_rna == 0 and c_lng == 0:
                continue
                
            p_ass = c_ass / n * 100 if n else 0
            p_ann = c_ann / n * 100 if n else 0
            p_rna = c_rna / n * 100 if n else 0
            p_lng = c_lng / n * 100 if n else 0
            
            phylum_metadata[taxid] = {
                'n_rows': n,
                'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
                's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
                'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
            }
            
    return phylum_metadata


# ---------------------------------------------------------------------------
def get_filtered_taxa_metadata(conn, root_taxid, target_rank, exclude_empty, filter_keys, filter_logic, sort_by_key, limit):
    """
    Pure SQL implementation of filtering, sorting, and metadata retrieval.
    Replaces Python-side multi-select filtering and sorting.
    Returns:
        phylum_metadata (dict): TaxID -> Metadata Dict (capped at limit)
        total_matches (int): How many rows matched the filters overall (before limit)
    """
    cursor = conn.cursor()
    
    # 1. Base Query with JOIN
    base_query = """
        FROM precomputed_taxa t
        INNER JOIN precomputed_clade_features f ON t.taxid = f.taxid
        WHERE t.root_taxid = ? AND t.target_rank = ?
    """
    params = [root_taxid, target_rank]
    
    # 2. Add Exclusion/Filters
    where_clauses = []
    if exclude_empty:
        where_clauses.append("(f.c_ass > 0 OR f.c_ann > 0 OR f.c_rna > 0 OR f.c_lng > 0)")
        
    if filter_keys:
        # e.g., filter_keys = ['c_ass', 'c_rna']
        conditions = [f"f.{k} > 0" for k in filter_keys]
        if filter_logic == "Match ALL (AND)":
            where_clauses.append("(" + " AND ".join(conditions) + ")")
        else:
            where_clauses.append("(" + " OR ".join(conditions) + ")")
            
    if where_clauses:
        base_query += " AND " + " AND ".join(where_clauses)
        
    # 3. First getting the Total Matches Count
    count_query = f"SELECT COUNT(*) {base_query}"
    cursor.execute(count_query, params)
    total_matches = cursor.fetchone()[0]
    
    if total_matches == 0:
        return {}, 0
        
    # 4. Secondary Sort logic based on sort_by_key to match original python logic
    # If sorting by 'c_ass', secondary is 's_ass'. Otherwise 'c_ass'.
    s_key = sort_by_key.replace('c_', 's_') if sort_by_key.startswith('c_') else 'c_ass'
    
    select_query = f"""
        SELECT t.taxid, f.n_rows, f.c_ass, f.c_ann, f.c_rna, f.c_lng, 
               f.s_ass, f.s_ann, f.s_rna, f.s_lng
        {base_query}
        ORDER BY f.{sort_by_key} DESC, f.{s_key} DESC
        LIMIT ?
    """
    params.append(limit)
    
    cursor.execute(select_query, params)
    results = cursor.fetchall()
    
    # Format identically to build_phylum_metadata
    phylum_metadata = {}
    for row in results:
        taxid = row[0]
        n, c_ass, c_ann, c_rna, c_lng = row[1], row[2], row[3], row[4], row[5]
        s_ass, s_ann, s_rna, s_lng = row[6], row[7], row[8], row[9]
        
        p_ass = c_ass / n * 100 if n else 0
        p_ann = c_ann / n * 100 if n else 0
        p_rna = c_rna / n * 100 if n else 0
        p_lng = c_lng / n * 100 if n else 0
        
        phylum_metadata[taxid] = {
            'n_rows': n,
            'c_ass': c_ass, 'c_ann': c_ann, 'c_rna': c_rna, 'c_lng': c_lng,
            's_ass': s_ass, 's_ann': s_ann, 's_rna': s_rna, 's_lng': s_lng,
            'p_ass': p_ass, 'p_ann': p_ann, 'p_rna': p_rna, 'p_lng': p_lng,
        }
        
    return phylum_metadata, total_matches
