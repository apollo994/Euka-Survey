import streamlit as st
import sqlite3
import os
import tempfile
import multiprocessing as mp

# Import local modules securely
from src import taxonomy
from src import visualization
from src import database
from src import utils
from src import ete_utils
from src.constants import (
    ALLOWED_RANKS,
    COMMON_CLADES,
    HARD_NODE_CAP,
    RENDER_SUBPROCESS_TIMEOUT_SECONDS,
    STANDARD_BREAKPOINTS,
)

# Constants
DB_PATH = "eukaryotes.db" # For local development
# Fetch from the automatic GitHub Release action
DB_DOWNLOAD_URL = "https://github.com/Cobos-Bioinfo/Euka-Survey/releases/latest/download/eukaryotes.db"  

# --- Streamlit Community Cloud App Name ---
st.set_page_config(page_title="EukaSurvey Platform", page_icon="🧬", layout="wide", initial_sidebar_state="expanded")

@st.cache_resource(show_spinner="Downloading Database (this happens once)...")
def get_db_ready():
    """Ensure the SQLite DB exists and is ready."""
    if utils.ensure_database(DB_PATH, DB_DOWNLOAD_URL):
        return True
    raise RuntimeError("Database download failed. Restart the app to retry.")

@st.cache_resource
def get_db_connection():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)

@st.cache_data(max_entries=200, show_spinner=False)
def get_taxa_count_cached(_conn, root_taxid, target_rank):
    """Fast SQL count for UI without loading rows into memory."""
    if not root_taxid or not target_rank:
        return 0
    try:
        cursor = _conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM precomputed_taxa WHERE root_taxid = ? AND target_rank = ?", (int(root_taxid), target_rank))
        result = cursor.fetchone()
        return result[0] if result else 0
    except sqlite3.OperationalError:
        return 0

@st.cache_data(max_entries=200, show_spinner=False)
def fetch_taxa_cached(_conn, root_taxid, target_rank):
    """Fetch taxa from DB if precomputed, safely falling back to ETE3."""
    if root_taxid is None or target_rank is None:
        return None
    try:
        cursor = _conn.cursor()
        cursor.execute("SELECT taxid, name FROM precomputed_taxa WHERE root_taxid = ? AND target_rank = ?", (int(root_taxid), target_rank))
        rows = cursor.fetchall()
        if rows:
            return [(row[0], row[1]) for row in rows]
    except sqlite3.OperationalError:
        pass  # Table might not exist yet
        
    return taxonomy.get_taxa_at_rank(root_taxid, target_rank)

@st.cache_data(max_entries=100, show_spinner=False)
def get_phylum_metadata_cached(_conn, taxids: tuple, exclude_empty: bool):
    """Wrapper to cache the heavy database computation of phylum/clade metadata."""
    return database.build_phylum_metadata(_conn, list(taxids), exclude_empty)

@st.cache_data(max_entries=50, show_spinner=False)
def get_filtered_taxa_metadata_cached(_conn, root_taxid, target_rank, exclude_empty, filter_keys_tuple, filter_logic, sort_by_key, top_n):
    """Wrapper to cache the pure SQL filtering and mapping retrieval."""
    return database.get_filtered_taxa_metadata(
        _conn, root_taxid, target_rank, exclude_empty, list(filter_keys_tuple), filter_logic, sort_by_key, top_n
    )

@st.cache_data(max_entries=50, show_spinner=False)
def generate_tree_svg_cached(phylum_metadata: dict, include_counts: bool) -> bytes | None:
    """Render the phylogenetic tree SVG in a spawned subprocess.

    PyQt5 requires its QApplication on the main thread of a process; Streamlit
    runs callbacks on worker threads, hence the subprocess. A timeout guards
    against a stuck Qt child hanging the Streamlit thread indefinitely.
    """
    tmp_fd, tmp_svg = tempfile.mkstemp(prefix="euka_tree_", suffix=".svg")
    os.close(tmp_fd)

    ctx = mp.get_context('spawn')
    p = ctx.Process(
        target=visualization.render_tree_in_process,
        args=(phylum_metadata, include_counts, tmp_svg),
    )
    p.start()
    p.join(timeout=RENDER_SUBPROCESS_TIMEOUT_SECONDS)

    try:
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
            if p.is_alive():
                p.kill()
            return None

        if p.exitcode != 0 or not os.path.exists(tmp_svg) or os.path.getsize(tmp_svg) == 0:
            return None

        with open(tmp_svg, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_svg):
            os.remove(tmp_svg)

# --------------------- Main App Logic --------------------- #
def main():
    # --- Main UI Layout ---
    st.title("EukaSurvey", anchor=False)
    st.subheader("The Genomic Resource Explorer for Eukaryotes", divider="blue", anchor=False)
    st.markdown("Visualize genomic data availability across the Eukaryotic Tree of Life.")

    # 1. Initialize dependencies
    try:
        get_db_ready()
    except RuntimeError:
        st.error("Could not download the database. Please refresh the page to try again.")
        st.stop()
            
    conn = get_db_connection()

    # 2. Sidebar Configuration 
    with st.sidebar:
        st.header("Help & Resources")
        
        with st.expander("How to use EukaSurvey", expanded=False):
            st.markdown("""
            **1. Define your Query**  
            Select a **Root Taxon ID** (e.g. Mammals' 40674) and a **Breakdown Rank** (e.g. Family) to slice the tree.
            
            **2. Review Summary**  
            The dashboard shows total counts for Assemblies, Annotations, and RNA-Seq across your query.
            
            **3. Filter & Sort**  
            In the *Tree Visualization* section, use **Filter Nodes** to skip taxa missing specific resources. You can combine filters with **AND/OR** logic.
            
            **4. Generate & Export**  
            Click **Generate Visualization** to view the tree. Use the **Data Export** buttons to download your query as a TSV or the tree as an SVG.
            """)

        st.subheader("Project", anchor=False)
        st.markdown("[View on GitHub](https://github.com/Cobos-Bioinfo/Euka-Survey) :material/open_in_new:")


    # 3. Query Configuration
    with st.container(border=True):
        st.header("Query Configuration", anchor=False)
        
        # Root taxon selection with common clades for convenience
        common_taxa_labels = [f"{name} ({tid})" for tid, name in COMMON_CLADES.items()]
        label_to_taxid = {f"{name} ({tid})": tid for tid, name in COMMON_CLADES.items()}

        q_cols = st.columns([1.5, 1, 1], gap="large")
        
        with q_cols[0]:
            choice = st.selectbox(
                "Root Taxon ID",
                ["Enter your own"] + common_taxa_labels,
                index=1,
                placeholder="Choose a valid NCBI Taxon ID",
                key="root_taxon_selection",
                help="Choose from a selection of commonly surveyed clades or enter any valid NCBI Taxon ID to define the root of your tree query."
            )

            # Handle the Root Taxon ID selection
            if choice == "Enter your own":
                root_taxid_input = st.text_input("Enter NCBI Taxon ID:", value="2759", placeholder="e.g. 2759 for Eukaryota")
                if root_taxid_input and str(root_taxid_input).strip().isdigit():
                    root_taxid = int(str(root_taxid_input).strip())
                else:
                    if root_taxid_input:
                        st.warning("Please enter a valid numeric Taxon ID.")
                    root_taxid = None
            else:
                root_taxid = label_to_taxid[choice]

        # Dynamic target rank Breakdown selection based on selected root taxon.
        # `taxonomy.resolve_valid_ranks` is @lru_cache'd, so this no longer
        # touches ETE3 on every rerun for the same root_taxid.
        valid_options = list(ALLOWED_RANKS)
        if root_taxid:
            try:
                valid_options = list(taxonomy.resolve_valid_ranks(root_taxid))
            except taxonomy.UnknownTaxonError:
                st.error("The selected TaxID could not be found. Please enter a valid TaxID or select from the common clades.")
                root_taxid = None

        if "rank_selection" not in st.session_state:
            st.session_state.rank_selection = valid_options[0] if valid_options else "phylum"

        with q_cols[1]:
            if valid_options:
                # Edge case: If previous selected rank was higher/equal (now invalid)
                # automatically change to highest level available rank.
                if st.session_state.rank_selection not in valid_options:
                    st.session_state.rank_selection = valid_options[0]
                    
                target_rank = st.selectbox(
                    "Breakdown by Rank",
                    valid_options, 
                    placeholder=None,
                    key="rank_selection",
                    help="Select the taxonomic rank to slice the tree. Only ranks below the selected root taxon are available."
                )
            else:
                # Edge case: Selected root taxon is species or lower
                st.warning("Selected root taxon is at the species level or lower. No further breakdown available.")
                target_rank = None

        root_name = ete_utils.get_name_from_taxid(root_taxid) if root_taxid else "Error" # type: ignore
        root_rank = ete_utils.get_rank_from_taxid(root_taxid) if root_taxid else "clade" # type: ignore

        # Provide reactive feedback on tree size
        query_taxids = []
        num_nodes = 0
        is_precomputed = False
        with q_cols[2]:
            st.write("") # small alignment spacing
            if root_taxid and target_rank and root_name != "Unknown":
                try:
                    num_nodes = get_taxa_count_cached(conn, root_taxid, target_rank)
                    if num_nodes > 0:
                        is_precomputed = True
                    else:
                        # Fallback for dynamic/non-canonical queries
                        query_taxa = fetch_taxa_cached(conn, root_taxid, target_rank)
                        if query_taxa:
                            query_taxids = [t[0] for t in query_taxa]
                            num_nodes = len(query_taxids)

                    if num_nodes > 0:
                        st.info(f"Tree size: **{num_nodes}** {target_rank} nodes", icon="🌲")
                        if num_nodes > 100:
                            st.caption("High node counts may take longer to compute and render.")
                    else:
                        st.warning(f"No {target_rank}s found under TaxID {root_taxid}.")
                except ValueError:
                    st.error("Invalid TaxID: Not found in database.")

    # --- Root Taxon Stat Summary --- #
    if root_taxid and root_name != "Unknown":
        st.header(f"Genomic Resource Summary", anchor=False)
        st.markdown(f"Overview of available resources across the entire _{root_name}_ {root_rank} (TaxID {root_taxid}).")
        
        # Fetch root stats dynamically
        root_metadata = get_phylum_metadata_cached(conn, tuple([root_taxid]), exclude_empty=False)
        if root_metadata and root_taxid in root_metadata:
            stats = root_metadata[root_taxid]
            
            # Prominent top-level metric for Total Species
            st.metric(
                label=f":material/groups: Total Species under {root_name}", 
                value=f"{int(stats['n_rows']):,}",
                help="Total number of unique species tracked in this clade"
            )
            
            # Balanced 4-column layout for detailed resource breakdowns
            cols = st.columns(4)
            
            # Assemblies Card
            with cols[0]:
                with st.container(border=True):
                    st.markdown("##### :material/database: :blue[Assemblies]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_ass']):,}",
                        help="Unique species with at least one genome assembly",
                    )
                    st.metric(
                        label="Total Assemblies", 
                        value=f"{int(stats['s_ass']):,}",
                        help="Total number of genome assemblies across all species"
                    )
                    ncbi_url = f"https://www.ncbi.nlm.nih.gov/datasets/genome/?taxon={root_taxid}"
                    st.markdown(f"[View on NCBI]({ncbi_url}) :material/open_in_new:")
                    
            # Annotations Card
            with cols[1]:
                with st.container(border=True):
                    st.markdown("##### :material/description: :orange[Annotations]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_ann']):,}",
                        help="Unique species with at least one functional annotation"
                    )
                    st.metric(
                        label="Total Annotations", 
                        value=f"{int(stats['s_ann']):,}",
                        help="Total number of annotated genomes across all species"
                    )
                    anno_url = f"https://genome.crg.es/annotrieve/annotations/details/?taxon={root_taxid}"
                    st.markdown(f"[View on Annotrieve]({anno_url}) :material/open_in_new:")
                    
            # RNA-Seq Card
            with cols[2]:
                with st.container(border=True):
                    st.markdown("##### :material/segment: :green[RNA-Seq (Any)]")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_rna']):,}",
                        help="Unique species with any RNA-Seq read data"
                    )
                    st.metric(
                        label="Total Runs", 
                        value=f"{int(stats['s_rna']):,}",
                        help="Total number of RNA-Seq runs across all species"
                    )
                    ena_rna_url = f"https://www.ebi.ac.uk/ena/browser/advanced-search?result=read_run&query=tax_tree({root_taxid})%20AND%20library_strategy%3D%22rna-seq%22&fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy&limit=0"
                    st.markdown(f"[View on ENA]({ena_rna_url}) :material/open_in_new:")
                    
            # Long-Read RNA Card
            with cols[3]:
                with st.container(border=True):
                    st.markdown("##### :material/reorder: :green[Long-Read RNA-Seq]", help="RNA-Seq experiments performed with Oxford Nanopore or PacBio SMRT platforms")
                    st.metric(
                        label="Species Covered", 
                        value=f"{int(stats['c_lng']):,}",
                        help="Unique species with at least one long-read RNA-Seq experiment"
                    )
                    st.metric(
                        label="Total Runs", 
                        value=f"{int(stats['s_lng']):,}",
                        help="Total number of Long-Read RNA-Seq runs across all species"
                    )
                    ena_lng_url = f"https://www.ebi.ac.uk/ena/browser/advanced-search?result=read_run&query=tax_tree({root_taxid})%20AND%20library_strategy%3D%22rna-seq%22%20AND%20(instrument_platform%3D%22OXFORD_NANOPORE%22%20OR%20instrument_platform%3D%22PACBIO_SMRT%22)&fields=run_accession%2Cexperiment_title%2Ctax_id%2Clibrary_strategy%2Cinstrument_platform&limit=0"
                    st.markdown(f"[View on ENA]({ena_lng_url}) :material/open_in_new:")
        else:
            st.warning("No data found for this Root Taxon.")
            
        # st.divider()
    elif root_taxid and root_name == "Unknown":
        st.error(f"TaxID {root_taxid} does not exist in the NCBI taxonomy database.")

    st.space("xsmall")
    # --- Tree Visualization Settings & Generation --- #
    if root_taxid and root_name != "Unknown" and num_nodes > 0:
        st.header("Tree Visualization", anchor=False)
        
        with st.form("tree_settings_form", border=True):
            st.subheader("Filter Nodes", anchor=False)
            filter_options = {
                "Assemblies": "c_ass",
                "Annotations": "c_ann",
                "RNA-Seq (Any)": "c_rna",
                "Long-Read RNA": "c_lng"
            }
            selected_filters = st.multiselect("Require data for (leaves node out if it lacks data)", list(filter_options.keys()), placeholder="Select features...")

            filter_logic_label = "Match ALL (AND)"
            if len(selected_filters) > 1:
                filter_logic_label = st.segmented_control("Condition", ["Match ALL (AND)", "Match ANY (OR)"], default="Match ALL (AND)")
            filter_logic = (
                database.FilterLogic.AND
                if filter_logic_label == "Match ALL (AND)"
                else database.FilterLogic.OR
            )
            
            st.subheader("Sorting & Limits", anchor=False)
            sort_options = {
                "Unique Species": "n_rows",
                "Species with Assemblies": "c_ass",
                "Species with Annotations": "c_ann",
                "Species with RNA-Seq (Any)": "c_rna",
                "Species with Long-Read RNA": "c_lng",
                "Assemblies": "s_ass",
                "Annotations": "s_ann",
                "RNA-Seq experiments (Any)": "s_rna",
                "Long-Read RNA-Seq experiments": "s_lng"
            }
            cols = st.columns(2)
            
            with cols[0]:
                sort_by_label = st.selectbox("Sort top nodes by number of ", list(sort_options.keys()), key="sort_by_selection")
                sort_by_key = sort_options[sort_by_label]
                
                exclude_empty = st.toggle("Exclude Empty Taxa (Zero data across all fields)", value=True)

            with cols[1]:
                # Dynamic node limit options based on availability and hard cap
                effective_max = min(num_nodes, HARD_NODE_CAP)

                # Filter down the breakpoints to only show those valid for the current tree size
                valid_options_limit = [str(b) for b in STANDARD_BREAKPOINTS if b < effective_max]
                
                # Add dynamic "All" and "Custom"
                valid_options_limit.append(f"All ({effective_max})")
                valid_options_limit.append("Custom")
                
                # Determine smart default index
                if "25" in valid_options_limit:
                    default_idx = valid_options_limit.index("25")
                else:
                    # If 25 is too high, pick the last numeric option before "All" (which is the effective max) or All.
                    default_idx = max(0, len(valid_options_limit) - 2)
                
                selected_limit = st.selectbox("Max nodes to display", valid_options_limit, index=default_idx, key="limit_selection", help=f"Hard cap set to {HARD_NODE_CAP} nodes for performance.")
                
                if selected_limit == "Custom":
                    top_n = st.number_input("Enter custom max nodes", min_value=2, max_value=effective_max, value=min(25, effective_max), step=1)
                elif selected_limit.startswith("All"):
                    top_n = effective_max
                else:
                    top_n = int(selected_limit)

                include_counts = st.toggle("Show Numeric Details in Tree", value=True, help="Toggle display of per-feature resource counts in the tree visualization.")

            submitted = st.form_submit_button("Generate Visualization", type="primary", icon=":material/account_tree:")

        # 3. Generate Visualization on button click
        if submitted:
            if not target_rank:
                st.error("Cannot generate tree: Root taxon is at species level or lower, no further taxonomic breakdown is possible.")
                st.stop()
            if num_nodes == 0:
                st.error(f"Cannot generate tree. No {target_rank}s found or invalid TaxID {root_taxid}.")
                st.stop()
                
            with st.spinner(f"Aggregating data and filtering clades..."):
                
                filter_keys = [filter_options[f] for f in selected_filters] if selected_filters else []
                
                if is_precomputed:
                    # SQL pushes filter/sort/limit down to SQLite.
                    phylum_metadata, total_matches = get_filtered_taxa_metadata_cached(
                        conn, root_taxid, target_rank, exclude_empty, tuple(filter_keys), filter_logic, sort_by_key, top_n
                    )
                else:
                    # Fallback for non-precomputed roots: fetch unfiltered metadata
                    # (cache key independent of filter knobs) then apply the same
                    # filter/sort/limit semantics as the SQL path in pure Python.
                    raw_metadata = get_phylum_metadata_cached(conn, tuple(query_taxids), exclude_empty=False)
                    phylum_metadata, total_matches = database.filter_sort_limit_metadata(
                        raw_metadata,
                        filter_keys=filter_keys,
                        filter_logic=filter_logic,
                        sort_by_key=sort_by_key,
                        top_n=top_n,
                        exclude_empty=exclude_empty,
                    )
                
                # Show exclusion statistics
                nodes_excluded = num_nodes - total_matches
                if nodes_excluded > 0:
                    st.info(f"**Nodes included:** {total_matches}/{num_nodes} "
                            f"({nodes_excluded} excluded due to filtering criteria)")
                
                if not phylum_metadata:
                    st.warning("No clades have data matching the criteria (or all were empty).")
                    st.stop()

            with st.spinner("Rendering phylogenetic tree..."):
                svg_bytes = generate_tree_svg_cached(phylum_metadata, include_counts)
                
                if svg_bytes is None:
                    st.error("Failed to render the tree. This is usually due to Qt/X11 rendering restrictions.")
                    st.stop()
                
                # st.image throws PIL.UnidentifiedImageError when fed raw SVG bytes.
                # Writing back to a temporary file allows Streamlit to bypass PIL via extension.
                tmp_fd, tmp_svg = tempfile.mkstemp(prefix="euka_display_", suffix=".svg")
                os.close(tmp_fd)
                try:
                    with open(tmp_svg, "wb") as f:
                        f.write(svg_bytes)
                    st.image(tmp_svg, use_container_width=True)
                finally:
                    if os.path.exists(tmp_svg):
                        os.remove(tmp_svg)
                
                st.download_button(
                    label="Download SVG Figure",
                    data=svg_bytes,
                    file_name=f"tree_{root_taxid}_{target_rank}.svg",
                    mime="image/svg+xml",
                    icon=":material/download:",
                    type="primary"
                )
                
                # Store success in session state to persist buttons
                st.session_state.rendered_taxid = root_taxid

    st.space("xsmall")
    # --- TSV Data Export Section --- #
    if root_taxid and target_rank and root_name != "Unknown" and num_nodes > 0:
        st.header("Export Data", anchor=False)
        st.write("Download the complete overview of the current query as a TSV file.")
        
        # In Streamlit, data for download_button is evaluated on render. 
        # We cache the generator to maintain UI performance instead of a 2-button prepare flow.
        tsv_filename = f"{root_name.replace(' ', '_')}_{target_rank}_data.tsv"
        
        # We pass the cacheable function over to the TSV generator to resolve the taxa inside 
        # the cached bounds and trigger the Streamlit Spinner, stopping it from freezing the UI.
        tsv_data = utils.generate_tsv(conn, root_taxid, target_rank, fetch_taxa_cached)
        
        st.download_button(
            label="Download TSV",
            data=tsv_data,
            file_name=tsv_filename,
            mime="text/tab-separated-values",
            icon=":material/download:",
            type="primary"
        )

if __name__ == "__main__":
    main()