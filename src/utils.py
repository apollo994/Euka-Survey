import os
import shutil
import urllib.request
import io
import csv
import streamlit as st
from src import database

_DOWNLOAD_TIMEOUT_SECONDS = 300


def ensure_database(db_path, download_url):
    """Ensure the SQLite DB exists, downloading it atomically if necessary.

    Downloads to `{db_path}.tmp` and atomically renames on success, so a
    partial download (e.g. network drop) never leaves a half-written file
    that future runs would treat as valid.
    """
    if os.path.exists(db_path):
        return True

    tmp_path = f"{db_path}.tmp"
    try:
        with urllib.request.urlopen(download_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response, \
             open(tmp_path, "wb") as out:
            shutil.copyfileobj(response, out)
        os.replace(tmp_path, db_path)
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        st.error(f"Could not download database: {e}")
        return False

@st.cache_data(show_spinner="Preparing data for download...")
def generate_tsv(_conn, root_taxid, target_rank, _fetch_func):
    """
    Generate a TSV string for the given query limit dynamically.
    """
    
    # We resolve the actual taxa inside the cached function to avoid hashing huge lists
    query_taxa = _fetch_func(_conn, root_taxid, target_rank)

    if not query_taxa:
        return ""
    
    query_taxids = [t[0] for t in query_taxa]
    taxa_names = {t[0]: t[1] for t in query_taxa}
    
    metadata = database.build_phylum_metadata(_conn, query_taxids, exclude_empty=False)
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    
    # Header in snake_case
    writer.writerow([
        "taxon_id", 
        "name", 
        "total_species", 
        "species_with_assemblies", 
        "species_with_annotations", 
        "species_with_rna_seq", 
        "species_with_long_read_rna_seq", 
        "total_assemblies", 
        "total_annotations", 
        "total_rna_seq", 
        "total_long_read_rna_seq"
    ])
    
    for taxid in query_taxids:
        name = taxa_names.get(taxid, "Unknown")
        stats = metadata.get(taxid, {})
        
        # Guard against missing stats implicitly returning missing keys
        writer.writerow([
            taxid,
            name,
            int(stats.get('n_rows', 0)),
            int(stats.get('c_ass', 0)),
            int(stats.get('c_ann', 0)),
            int(stats.get('c_rna', 0)),
            int(stats.get('c_lng', 0)),
            int(stats.get('s_ass', 0)),
            int(stats.get('s_ann', 0)),
            int(stats.get('s_rna', 0)),
            int(stats.get('s_lng', 0))
        ])
        
    return output.getvalue()
