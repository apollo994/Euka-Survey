"""Sidebar: help + project links. No app state — pure content."""

import streamlit as st


def render_sidebar() -> None:
    with st.sidebar:
        st.divider()
        st.header("Help & Resources")

        with st.expander("How to use EukaSurvey", expanded=False):
            st.markdown("""
            **1. Define your Query**
            Select a **Root Taxon ID** (e.g. Mammals' 40674) and a **Breakdown Rank** (e.g. Family) to slice the tree.

            **2. Review Summary**
            The dashboard shows total counts for Assemblies, Annotations, and RNA-Seq across your query.

            **3. Filter & Sort**
            In the *Explore Results* section, use **Filter Nodes** to skip taxa missing specific resources. You can combine filters with **AND/OR** logic.

            **4. Generate, Explore & Export**
            Click **Generate Visualization** for the **🌳 Tree** and a sortable **📊 Table** of the same clades. Download the tree as SVG, the table as TSV, or the full query from **Export Data**.
            """)

        st.subheader("Project", anchor=False)
        st.markdown("[View on GitHub](https://github.com/Cobos-Bioinfo/Euka-Survey) :material/open_in_new:")
