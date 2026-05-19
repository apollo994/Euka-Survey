"""
Fetches descendant taxonomic IDs for a given parent taxonomic ID.
Utilizes the local NCBI taxonomy database via the ete3 library.
"""

from ete3 import NCBITaxa

def get_name_from_taxid(taxid: int) -> str:
    """Get the scientific name for a given taxonomic ID."""
    if taxid is None or not isinstance(taxid, int):
        raise ValueError("Invalid taxid provided. Must be a non-null integer.")
    ncbi = NCBITaxa()
    names = ncbi.get_taxid_translator([taxid])
    return names.get(taxid, "Unknown")

def get_rank_from_taxid(taxid: int) -> str:
    """Get the taxonomic rank for a given taxonomic ID."""
    if taxid is None or not isinstance(taxid, int):
        return "clade"
    ncbi = NCBITaxa()
    ranks = ncbi.get_rank([taxid])
    return ranks.get(taxid, "clade")
