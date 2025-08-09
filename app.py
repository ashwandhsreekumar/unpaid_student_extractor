import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import os
from pathlib import Path
import tempfile
import zipfile
from fee_extractor import FeeDefaulterExtractor

def format_indian_currency(amount):
    """Format number in Indian currency style (lakhs and crores)"""
    amount = int(amount)
    
    if amount < 0:
        return f"-₹{format_indian_currency(-amount)[1:]}"
    
    # Convert to string and reverse for easier processing
    s = str(amount)[::-1]
    
    # Add commas - first after 3 digits, then every 2 digits
    result = []
    for i, digit in enumerate(s):
        if i == 3:
            result.append(',')
        elif i > 3 and (i - 3) % 2 == 0:
            result.append(',')
        result.append(digit)
    
    return f"₹{(''.join(result))[::-1]}"

# Page configuration
st.set_page_config(
    page_title="Fee Defaulter Finder",
    page_icon="🎓",
    layout="wide"
)

# Custom CSS
st.markdown("""
    <style>
    .stMetric {
        background-color: #f0f2f6;
        padding: 10px;
        border-radius: 5px;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
    }
    </style>
""", unsafe_allow_html=True)

def create_visualizations(summary_data, school_name, total_students=None):
    """Create visualizations for the dashboard"""
    if summary_data.empty and not total_students:
        return None, None, None
    
    # Payment status distribution
    # If total_students is provided, use it; otherwise use summary data length
    if total_students:
        defaulters = len(summary_data) if not summary_data.empty else 0
        paid_students = total_students - defaulters
    else:
        # Fallback to old logic
        total_students = len(summary_data)
        defaulters = len(summary_data[summary_data['Total Outstanding'] > 0])
        paid_students = total_students - defaulters
    
    fig_pie = go.Figure(data=[go.Pie(
        labels=['Defaulters', 'Paid'],
        values=[defaulters, paid_students],
        hole=.3,
        marker_colors=['#ff6b6b', '#51cf66']
    )])
    fig_pie.update_layout(
        title=f"Payment Status Distribution - {school_name}",
        height=400
    )
    
    # Defaulters by grade
    grade_counts = summary_data[summary_data['Total Outstanding'] > 0].groupby('Grade').size().reset_index(name='Count')
    fig_bar = px.bar(
        grade_counts, 
        x='Grade', 
        y='Count',
        title=f"Defaulters by Grade - {school_name}",
        color='Count',
        color_continuous_scale='RdYlGn_r'
    )
    fig_bar.update_layout(height=400)
    
    # Outstanding amount by grade
    grade_amounts = summary_data.groupby('Grade')['Total Outstanding'].sum().reset_index()
    fig_amount = px.bar(
        grade_amounts,
        x='Grade',
        y='Total Outstanding',
        title=f"Outstanding Amount by Grade - {school_name}",
        color='Total Outstanding',
        color_continuous_scale='Blues',
        text='Total Outstanding'
    )
    # Format text for Indian currency in the chart
    grade_amounts['Total Outstanding Text'] = grade_amounts['Total Outstanding'].apply(format_indian_currency)
    fig_amount.update_traces(
        text=grade_amounts['Total Outstanding Text'],
        texttemplate='%{text}',
        textposition='outside'
    )
    fig_amount.update_layout(height=400)
    
    return fig_pie, fig_bar, fig_amount

def process_uploaded_files(contacts_file, invoices_file):
    """Process uploaded files and generate reports"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save uploaded files
        contacts_path = os.path.join(temp_dir, "Contacts.csv")
        invoices_path = os.path.join(temp_dir, "Invoice.csv")
        output_path = os.path.join(temp_dir, "output")
        
        with open(contacts_path, "wb") as f:
            f.write(contacts_file.getbuffer())
        with open(invoices_path, "wb") as f:
            f.write(invoices_file.getbuffer())
        
        # Run extraction with fixed logic
        extractor = FeeDefaulterExtractor(
            contacts_path=contacts_path,
            invoices_path=invoices_path,
            output_base_path=output_path
        )
        
        # Load and process data
        extractor.load_data()
        # Process invoices with proportional balance allocation
        defaulter_invoices = extractor.process_invoices()
        
        # Note: Stats will be shown in the console/logs, not in the UI during processing
        
        # Process each school
        results = {}
        school_stats = {}
        for school in ['Excel Global School', 'Excel Central School']:
            summary_df = extractor.create_student_summary(defaulter_invoices, school)
            
            # Get total students in school from contacts
            school_total = len(extractor.contacts_df[
                extractor.contacts_df['School'] == school
            ]['Contact ID'].unique())
            
            if not summary_df.empty:
                extractor.save_reports(summary_df, school)
                results[school] = summary_df
            else:
                results[school] = pd.DataFrame()
            
            school_stats[school] = {
                'total_students': school_total,
                'defaulters': len(summary_df) if not summary_df.empty else 0
            }
        
        # Create zip file with all reports
        zip_path = os.path.join(temp_dir, "fee_defaulter_reports.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(output_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_path)
                    zipf.write(file_path, arcname)
        
        with open(zip_path, "rb") as f:
            zip_data = f.read()
        
        return results, zip_data, school_stats

def main():
    st.title("🎓 Fee Defaulter Finder")
    st.markdown("### Excel Group of Schools - Fee Management System")
    
    # Initialize session state
    if 'processed' not in st.session_state:
        st.session_state.processed = False
        st.session_state.results = None
        st.session_state.zip_data = None
        st.session_state.school_stats = None
    
    # Sidebar
    with st.sidebar:
        st.header("📁 Upload Files")
        
        contacts_file = st.file_uploader(
            "Upload Contacts.csv",
            type=['csv'],
            help="Upload the contacts CSV file from Zoho Books",
            key="contacts_uploader"
        )
        
        invoices_file = st.file_uploader(
            "Upload Invoice.csv",
            type=['csv'],
            help="Upload the invoice CSV file from Zoho Books",
            key="invoices_uploader"
        )
        
        process_button = st.button("🚀 Process Files", type="primary", use_container_width=True)
        
        # Reset button
        if st.session_state.processed:
            if st.button("🔄 Reset", type="secondary", use_container_width=True):
                st.session_state.processed = False
                st.session_state.results = None
                st.session_state.zip_data = None
                st.session_state.school_stats = None
                st.rerun()
        
        st.divider()
        
        st.info(f"**Current Date:** {date.today().strftime('%B %d, %Y')}")
        
        st.markdown("""
        ### 📋 Instructions
        1. Upload both CSV files
        2. Click 'Process Files'
        3. View results and download reports
        
        ### 📊 Report Types
        - **Teachers Report**: Shows payment status (Paid/Unpaid)
        - **Accounts Report**: Shows outstanding amounts
        """)
    
    # Main content area
    if process_button and contacts_file and invoices_file:
        with st.spinner("Processing files..."):
            try:
                results, zip_data, school_stats = process_uploaded_files(contacts_file, invoices_file)
                
                # Store in session state
                st.session_state.processed = True
                st.session_state.results = results
                st.session_state.zip_data = zip_data
                st.session_state.school_stats = school_stats
                
                st.success("✅ Files processed successfully! Using proportional balance allocation for accurate calculations.")
                st.rerun()
                
            except Exception as e:
                st.error(f"❌ Error processing files: {str(e)}")
                st.exception(e)
    
    elif st.session_state.processed and st.session_state.results:
        # Display results from session state
        results = st.session_state.results
        zip_data = st.session_state.zip_data
        
        # Download button for all reports
        st.download_button(
            label="📥 Download All Reports (ZIP)",
            data=zip_data,
            file_name=f"fee_defaulter_reports_{date.today().strftime('%Y%m%d')}.zip",
            mime="application/zip",
            use_container_width=True
        )
        
        # Tabs for each school
        tab1, tab2 = st.tabs(["Excel Central School", "Excel Global School"])
        
        with tab1:
            if not results['Excel Central School'].empty:
                summary = results['Excel Central School']
                
                # Metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    total_in_school = st.session_state.school_stats['Excel Central School']['total_students'] if st.session_state.school_stats else len(summary)
                    st.metric("Total Students", total_in_school)
                with col2:
                    defaulters = len(summary[summary['Total Outstanding'] > 0])
                    st.metric("Defaulters", defaulters)
                with col3:
                    st.metric("Total Outstanding", format_indian_currency(summary['Total Outstanding'].sum()))
                with col4:
                    st.metric("Grades Affected", summary['Grade'].nunique())
                        
                # Visualizations
                st.divider()
                total_students = st.session_state.school_stats['Excel Central School']['total_students'] if st.session_state.school_stats else None
                fig_pie, fig_bar, fig_amount = create_visualizations(summary, "Excel Central School", total_students)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.plotly_chart(fig_pie, use_container_width=True)
                with col2:
                    st.plotly_chart(fig_bar, use_container_width=True)
                
                st.plotly_chart(fig_amount, use_container_width=True)
                        
                # Data table with filters
                st.divider()
                st.subheader("📋 Defaulter Details")
                
                # Search bar
                search_query = st.text_input(
                    "🔍 Search by Student Name",
                    placeholder="Type student name to search...",
                    key="ecs_search"
                )
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    selected_grade = st.selectbox(
                        "Filter by Grade",
                        ["All"] + sorted(summary['Grade'].unique().tolist()),
                        key="ecs_grade"
                    )
                with col2:
                    selected_section = st.selectbox(
                        "Filter by Section",
                        ["All"] + sorted(summary['Section'].unique().tolist()),
                        key="ecs_section"
                    )
                with col3:
                    view_type = st.selectbox(
                        "View Type",
                        ["Teachers View", "Accounts View"],
                        key="ecs_view"
                    )
                
                # Filter data
                filtered_data = summary.copy()
                
                # Apply search filter
                if search_query:
                    filtered_data = filtered_data[
                        filtered_data['Student Name'].str.contains(search_query, case=False, na=False)
                    ]
                
                if selected_grade != "All":
                    filtered_data = filtered_data[filtered_data['Grade'] == selected_grade]
                if selected_section != "All":
                    filtered_data = filtered_data[filtered_data['Section'] == selected_section]
                
                # Display appropriate view
                if view_type == "Teachers View":
                    # Get fee columns from the actual data
                    fee_columns = [col for col in filtered_data.columns 
                                 if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                               'Grade', 'Section', 'Total Outstanding']]
                    display_cols = ['Student Name', 'Enrollment No', 'Grade', 'Section']
                    for col in fee_columns:
                        if col in filtered_data.columns:
                            filtered_data[col] = filtered_data[col].apply(
                                lambda x: 'Unpaid' if x > 0 else 'Paid'
                            )
                            display_cols.append(col)
                    st.dataframe(filtered_data[display_cols], use_container_width=True)
                else:
                    # Format currency columns for display
                    display_data = filtered_data.copy()
                    currency_cols = [col for col in display_data.columns 
                                   if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                                 'Grade', 'Section']]
                    for col in currency_cols:
                        if col in display_data.columns and display_data[col].dtype in ['int64', 'float64']:
                            display_data[col] = display_data[col].apply(
                                lambda x: format_indian_currency(x) if x > 0 else '₹0' if x == 0 else ''
                            )
                    st.dataframe(display_data, use_container_width=True)
            else:
                st.info("No defaulters found for Excel Central School")
        
        with tab2:
            if not results['Excel Global School'].empty:
                summary = results['Excel Global School']
                
                # Metrics
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    total_in_school = st.session_state.school_stats['Excel Global School']['total_students'] if st.session_state.school_stats else len(summary)
                    st.metric("Total Students", total_in_school)
                with col2:
                    defaulters = len(summary[summary['Total Outstanding'] > 0])
                    st.metric("Defaulters", defaulters)
                with col3:
                    st.metric("Total Outstanding", format_indian_currency(summary['Total Outstanding'].sum()))
                with col4:
                    st.metric("Grades Affected", summary['Grade'].nunique())
                        
                # Visualizations
                st.divider()
                total_students = st.session_state.school_stats['Excel Global School']['total_students'] if st.session_state.school_stats else None
                fig_pie, fig_bar, fig_amount = create_visualizations(summary, "Excel Global School", total_students)
                
                col1, col2 = st.columns(2)
                with col1:
                    st.plotly_chart(fig_pie, use_container_width=True)
                with col2:
                    st.plotly_chart(fig_bar, use_container_width=True)
                
                st.plotly_chart(fig_amount, use_container_width=True)
                
                # Data table with filters
                st.divider()
                st.subheader("📋 Defaulter Details")
                
                # Search bar
                search_query = st.text_input(
                    "🔍 Search by Student Name",
                    placeholder="Type student name to search...",
                    key="egs_search"
                )
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    selected_grade = st.selectbox(
                        "Filter by Grade",
                        ["All"] + sorted(summary['Grade'].unique().tolist()),
                        key="egs_grade"
                    )
                with col2:
                    selected_section = st.selectbox(
                        "Filter by Section",
                        ["All"] + sorted(summary['Section'].unique().tolist()),
                        key="egs_section"
                    )
                with col3:
                    view_type = st.selectbox(
                        "View Type",
                        ["Teachers View", "Accounts View"],
                        key="egs_view"
                    )
                
                # Filter data
                filtered_data = summary.copy()
                
                # Apply search filter
                if search_query:
                    filtered_data = filtered_data[
                        filtered_data['Student Name'].str.contains(search_query, case=False, na=False)
                    ]
                
                if selected_grade != "All":
                    filtered_data = filtered_data[filtered_data['Grade'] == selected_grade]
                if selected_section != "All":
                    filtered_data = filtered_data[filtered_data['Section'] == selected_section]
                
                # Display appropriate view
                if view_type == "Teachers View":
                    # Get fee columns from the actual data
                    fee_columns = [col for col in filtered_data.columns 
                                 if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                               'Grade', 'Section', 'Total Outstanding']]
                    display_cols = ['Student Name', 'Enrollment No', 'Grade', 'Section']
                    for col in fee_columns:
                        if col in filtered_data.columns:
                            filtered_data[col] = filtered_data[col].apply(
                                lambda x: 'Unpaid' if x > 0 else 'Paid'
                            )
                            display_cols.append(col)
                    st.dataframe(filtered_data[display_cols], use_container_width=True)
                else:
                    # Format currency columns for display
                    display_data = filtered_data.copy()
                    currency_cols = [col for col in display_data.columns 
                                   if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                                 'Grade', 'Section']]
                    for col in currency_cols:
                        if col in display_data.columns and display_data[col].dtype in ['int64', 'float64']:
                            display_data[col] = display_data[col].apply(
                                lambda x: format_indian_currency(x) if x > 0 else '₹0' if x == 0 else ''
                            )
                    st.dataframe(display_data, use_container_width=True)
            else:
                st.info("No defaulters found for Excel Global School")
    
    elif process_button and (not contacts_file or not invoices_file):
        st.warning("⚠️ Please upload both CSV files before processing")
    
    else:
        # Welcome screen
        st.markdown("""
        ## Welcome to Fee Defaulter Finder
        
        This application helps Excel Group of Schools identify and manage pending fee payments efficiently.
        
        ### Features:
        - 📊 **Automatic Extraction**: Identifies students with overdue fees
        - 🏫 **Multi-School Support**: Handles both Excel Global School and Excel Central School
        - 📅 **Dynamic Date Handling**: Shows only fees due up to current date
        - 👩‍🏫 **Teacher Reports**: Simple payment status view for class teachers
        - 💰 **Accounts Reports**: Detailed outstanding amounts for accounts team
        - 📈 **Visual Analytics**: Charts and graphs for quick insights
        - 📥 **Export Options**: Download reports in CSV format
        
        ### Get Started:
        1. Upload your Contacts.csv and Invoice.csv files using the sidebar
        2. Click the "Process Files" button
        3. View and download the generated reports
        """)

if __name__ == "__main__":
    main()