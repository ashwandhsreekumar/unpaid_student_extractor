import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import os
from pathlib import Path
import tempfile
import zipfile
import io
from fee_extractor import FeeDefaulterExtractor
from initial_fee_defaulters import InitialFeeDefaulterExtractor

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
    
    # Define proper grade order
    grade_order = ['Pre-KG', 'LKG', 'UKG'] + [f'Grade {str(i).zfill(2)}' for i in range(1, 13)]
    
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
    # Sort by grade order
    grade_counts['Grade_Order'] = grade_counts['Grade'].map({grade: i for i, grade in enumerate(grade_order)})
    grade_counts = grade_counts.sort_values('Grade_Order')
    
    fig_bar = px.bar(
        grade_counts, 
        x='Grade', 
        y='Count',
        title=f"Defaulters by Grade - {school_name}",
        color='Count',
        color_continuous_scale='RdYlGn_r'
    )
    fig_bar.update_layout(height=400)
    fig_bar.update_xaxes(categoryorder='array', categoryarray=[g for g in grade_order if g in grade_counts['Grade'].values])
    
    # Outstanding amount by grade
    grade_amounts = summary_data.groupby('Grade')['Total Outstanding'].sum().reset_index()
    # Sort by grade order
    grade_amounts['Grade_Order'] = grade_amounts['Grade'].map({grade: i for i, grade in enumerate(grade_order)})
    grade_amounts = grade_amounts.sort_values('Grade_Order')
    
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
    fig_amount.update_layout(height=600)
    fig_amount.update_xaxes(categoryorder='array', categoryarray=[g for g in grade_order if g in grade_amounts['Grade'].values])
    
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
        
        # Process payment analytics data - pass the contacts data for accurate counts
        # Note: create_payment_analytics method doesn't exist in FeeDefaulterExtractor
        payment_analytics = None

        # Create ZIP file for downloads
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add all generated reports to the ZIP
            for root, dirs, files in os.walk(output_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, output_path)
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()

        return results, zip_data, school_stats, payment_analytics

def process_initial_fee_defaulters(contacts_file, invoices_file, payments_file):
    """Process files for initial fee and opening balance defaulters"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Save uploaded files
        contacts_path = os.path.join(temp_dir, "Contacts.csv")
        invoices_path = os.path.join(temp_dir, "Invoice.csv")
        payments_path = os.path.join(temp_dir, "Customer_Payment.csv")
        output_path = os.path.join(temp_dir, "output")

        with open(contacts_path, "wb") as f:
            f.write(contacts_file.getbuffer())
        with open(invoices_path, "wb") as f:
            f.write(invoices_file.getbuffer())
        with open(payments_path, "wb") as f:
            f.write(payments_file.getbuffer())

        # Run initial fee defaulter extraction
        extractor = InitialFeeDefaulterExtractor(
            contacts_path=contacts_path,
            invoices_path=invoices_path,
            payments_path=payments_path,
            output_base_path=output_path
        )

        # Process data and get results
        defaulters_df = extractor.extract_initial_fee_defaulters()

        # Create ZIP file for downloads
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            if not defaulters_df.empty:
                # Save the main report
                main_report_path = os.path.join(output_path, 'fee_and_opening_balance_defaulters.csv')
                extractor.save_defaulters_report(defaulters_df)

                if os.path.exists(main_report_path):
                    zip_file.write(main_report_path, 'fee_and_opening_balance_defaulters.csv')

        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()

        return defaulters_df, zip_data

def process_payment_analytics(invoices_path, contacts_path):
    """Process payment analytics from invoice data"""
    import pandas as pd
    df = pd.read_csv(invoices_path)
    contacts_df = pd.read_csv(contacts_path)
    
    # Get ALL invoices grouped by invoice number to avoid duplicates
    all_invoices = df.groupby('Invoice Number').agg({
        'Total': 'first',
        'Balance': 'first',
        'School': 'first',
        'Grade': 'first',
        'Section': 'first',
        'Customer Name': 'first',
        'Customer ID': 'first',
        'Invoice Date': 'first',
        'Invoice Status': 'first'
    }).reset_index()
    
    # Calculate total outstanding balance per student across ALL their invoices
    # First get the latest grade/section for each student (in case they changed grades)
    student_latest = all_invoices.sort_values('Invoice Date').groupby('Customer ID').agg({
        'School': 'last',
        'Grade': 'last', 
        'Section': 'last',
        'Customer Name': 'last'
    }).reset_index()
    
    # Calculate total balances per student
    student_totals = all_invoices.groupby('Customer ID').agg({
        'Balance': 'sum',
        'Total': 'sum'
    }).reset_index()
    
    # Merge to get complete student data
    student_balances = pd.merge(student_latest, student_totals, on='Customer ID')
    
    # Students who have FULLY paid (zero total outstanding balance)
    fully_paid_students = student_balances[student_balances['Balance'] == 0].copy()
    
    # Get paid invoices for collection amounts
    paid_invoices = all_invoices[all_invoices['Balance'] == 0].copy()
    
    # Calculate total collections (sum of all paid invoices)
    total_collected = paid_invoices['Total'].sum()
    
    # Calculate total payments by school (from paid invoices)
    school_totals = paid_invoices.groupby('School')['Total'].sum().to_dict()
    
    # Calculate payments by grade for each school (from paid invoices)
    grade_payments = paid_invoices.groupby(['School', 'Grade'])['Total'].sum().reset_index()
    
    # Calculate monthly collections
    paid_invoices['Invoice Date'] = pd.to_datetime(paid_invoices['Invoice Date'])
    paid_invoices['Month'] = paid_invoices['Invoice Date'].dt.strftime('%B %Y')
    monthly_payments = paid_invoices.groupby(['School', 'Month'])['Total'].sum().reset_index()
    
    # Count FULLY PAID students by section (zero outstanding balance)
    students_paid_by_section = fully_paid_students.groupby(['School', 'Grade', 'Section']).size().reset_index(name='Students_Paid')
    
    # Add students without invoices to the paid count
    # Get students from contacts who don't have any invoices
    all_student_ids_with_invoices = set(all_invoices['Customer ID'].unique())
    contacts_without_invoices = contacts_df[~contacts_df['Contact ID'].isin(all_student_ids_with_invoices)].copy()
    
    if not contacts_without_invoices.empty:
        # Count students without invoices by section
        no_invoice_by_section = contacts_without_invoices.groupby(['School', 'Grade', 'Section']).size().reset_index(name='Students_Paid')
        
        # Combine with fully paid students
        students_paid_by_section = pd.concat([students_paid_by_section, no_invoice_by_section]).groupby(['School', 'Grade', 'Section'])['Students_Paid'].sum().reset_index()
    
    # Get actual total students from contacts
    total_students_by_school = contacts_df.groupby('School')['Contact ID'].nunique().to_dict()
    
    # Count fully paid students by school (from invoices)
    students_paid_from_invoices = fully_paid_students.groupby('School')['Customer ID'].nunique().to_dict()
    
    # Count students with invoices by school
    students_with_invoices_by_school = all_invoices.groupby('School')['Customer ID'].nunique().to_dict()
    
    # Calculate students without invoices (they have no dues, so count as "paid")
    students_without_invoices_by_school = {}
    students_paid_by_school = {}
    
    for school in total_students_by_school.keys():
        total = total_students_by_school[school]
        with_invoices = students_with_invoices_by_school.get(school, 0)
        without_invoices = total - with_invoices
        students_without_invoices_by_school[school] = without_invoices
        
        # Total "paid" = fully paid from invoices + students without any invoices
        paid_from_invoices = students_paid_from_invoices.get(school, 0)
        students_paid_by_school[school] = paid_from_invoices + without_invoices
        
        if school not in school_totals:
            school_totals[school] = 0
    
    # Create a combined list of fully paid students (including those without invoices)
    if not contacts_without_invoices.empty:
        # Convert contacts without invoices to same format as fully_paid_students
        contacts_no_inv_formatted = contacts_without_invoices.rename(columns={
            'Contact ID': 'Customer ID',
            'Company Name': 'Customer Name'  # Use Company Name from contacts as Customer Name
        })
        contacts_no_inv_formatted['Balance'] = 0
        contacts_no_inv_formatted['Total'] = 0
        
        # Select only columns that exist
        required_cols = ['Customer ID', 'School', 'Grade', 'Section', 'Customer Name', 'Balance', 'Total']
        available_cols = [col for col in required_cols if col in contacts_no_inv_formatted.columns]
        
        # If Customer Name doesn't exist, use Contact Name or Company Name
        if 'Customer Name' not in contacts_no_inv_formatted.columns:
            if 'Contact Name' in contacts_no_inv_formatted.columns:
                contacts_no_inv_formatted['Customer Name'] = contacts_no_inv_formatted['Contact Name']
            else:
                contacts_no_inv_formatted['Customer Name'] = 'N/A'
        
        fully_paid_all = pd.concat([fully_paid_students, contacts_no_inv_formatted[available_cols]], ignore_index=True)
    else:
        fully_paid_all = fully_paid_students
    
    return {
        'paid_invoices': paid_invoices,
        'school_totals': school_totals,
        'grade_payments': grade_payments,
        'monthly_payments': monthly_payments,
        'total_collected': total_collected,
        'students_paid_by_section': students_paid_by_section,
        'total_students_by_school': total_students_by_school,
        'students_paid_by_school': students_paid_by_school,
        'fully_paid_students': fully_paid_all,
        'students_without_invoices_by_school': students_without_invoices_by_school
    }

def main():
    st.title("🎓 Fee Defaulter Finder")
    st.markdown("### Excel Group of Schools - Fee Management System")
    
    # Initialize session state
    if 'processed' not in st.session_state:
        st.session_state.processed = False
        st.session_state.results = None
        st.session_state.zip_data = None
        st.session_state.school_stats = None
        st.session_state.payment_analytics = None
        st.session_state.initial_fee_processed = False
        st.session_state.initial_fee_results = None
        st.session_state.initial_fee_zip_data = None
    
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

        payments_file = st.file_uploader(
            "Upload Customer_Payment.csv",
            type=['csv'],
            help="Upload the customer payment CSV file from Zoho Books (for opening balance analysis)",
            key="payments_uploader"
        )

        process_button = st.button("🚀 Process Files", type="primary", use_container_width=True)
        initial_fee_button = st.button("💰 Process Initial Fee & Opening Balance Defaulters", type="secondary", use_container_width=True)
        
        # Reset button
        if st.session_state.processed or st.session_state.initial_fee_processed:
            if st.button("🔄 Reset", type="secondary", use_container_width=True):
                st.session_state.processed = False
                st.session_state.results = None
                st.session_state.zip_data = None
                st.session_state.school_stats = None
                st.session_state.payment_analytics = None
                st.session_state.initial_fee_processed = False
                st.session_state.initial_fee_results = None
                st.session_state.initial_fee_zip_data = None
                st.rerun()
        
        st.divider()
        
        st.info(f"**Current Date:** {date.today().strftime('%B %d, %Y')}")
        
        st.markdown("""
        ### 📋 Instructions
        1. Upload CSV files (Contacts & Invoice required for basic processing)
        2. Choose processing type:
           - **🚀 Process Files**: Standard fee defaulter analysis
           - **💰 Process Initial Fee & Opening Balance**: Advanced analysis with opening balance tracking
        3. View results and download reports

        ### 📊 Report Types
        - **Teachers Report**: Shows payment status (Paid/Unpaid)
        - **Accounts Report**: Shows outstanding amounts
        - **💰 Fee & Opening Balance Report**: Combined initial fee + opening balance defaulters
        """)
    
    # Main content area
    if process_button and contacts_file and invoices_file:
        with st.spinner("Processing files..."):
            try:
                results, zip_data, school_stats, payment_analytics = process_uploaded_files(contacts_file, invoices_file)

                # Store in session state
                st.session_state.processed = True
                st.session_state.results = results
                st.session_state.zip_data = zip_data
                st.session_state.school_stats = school_stats
                st.session_state.payment_analytics = payment_analytics

                st.success("✅ Files processed successfully! Using proportional balance allocation for accurate calculations.")
                st.rerun()

            except Exception as e:
                st.error(f"❌ Error processing files: {str(e)}")
                st.exception(e)

    # Process initial fee and opening balance defaulters
    if initial_fee_button and contacts_file and invoices_file and payments_file:
        with st.spinner("Processing initial fee and opening balance defaulters..."):
            try:
                initial_fee_results, initial_fee_zip_data = process_initial_fee_defaulters(contacts_file, invoices_file, payments_file)

                # Store in session state
                st.session_state.initial_fee_processed = True
                st.session_state.initial_fee_results = initial_fee_results
                st.session_state.initial_fee_zip_data = initial_fee_zip_data

                st.success("✅ Initial fee and opening balance defaulters processed successfully!")
                st.rerun()

            except Exception as e:
                st.error(f"❌ Error processing initial fee defaulters: {str(e)}")
                st.exception(e)

    # Display initial fee defaulters results
    elif st.session_state.initial_fee_processed and st.session_state.initial_fee_results is not None:
        initial_fee_results = st.session_state.initial_fee_results
        initial_fee_zip_data = st.session_state.initial_fee_zip_data

        # Download button for initial fee defaulters report
        st.download_button(
            label="📥 Download Fee & Opening Balance Defaulters Report (CSV)",
            data=initial_fee_zip_data,
            file_name=f"fee_and_opening_balance_defaulters_{date.today().strftime('%Y%m%d')}.zip",
            mime="application/zip",
            use_container_width=True
        )

        # Display summary metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            total_defaulters = len(initial_fee_results)
            st.metric("Total Defaulters", total_defaulters)
        with col2:
            fee_defaulters = len(initial_fee_results[initial_fee_results['Status'] == 'Initial Fee Not Paid'])
            st.metric("Initial Fee Defaulters", fee_defaulters)
        with col3:
            opening_balance_defaulters = len(initial_fee_results[initial_fee_results['Status'] == 'Opening Balance Not Fully Paid'])
            st.metric("Opening Balance Defaulters", opening_balance_defaulters)
        with col4:
            if opening_balance_defaulters > 0:
                total_outstanding = initial_fee_results[
                    initial_fee_results['Status'] == 'Opening Balance Not Fully Paid'
                ]['Remaining Opening Balance'].sum()
                st.metric("Total Outstanding Balance", f"₹{total_outstanding:,.0f}")
            else:
                st.metric("Total Outstanding Balance", "₹0")

        # Display results table
        st.subheader("📋 Fee & Opening Balance Defaulters")

        # Filter options
        col1, col2, col3 = st.columns(3)
        with col1:
            selected_school = st.selectbox(
                "Filter by School:",
                ["All Schools"] + sorted(list(initial_fee_results['School'].unique())),
                key="school_filter_initial"
            )
        with col2:
            selected_status = st.selectbox(
                "Filter by Status:",
                ["All"] + sorted(list(initial_fee_results['Status'].unique())),
                key="status_filter_initial"
            )
        with col3:
            # Get unique grades and sort them properly
            all_grades = list(initial_fee_results['Grade'].unique())

            # Define grade ordering function
            def grade_sort_key(grade):
                if grade == 'Pre-KG':
                    return (0, 0)
                elif grade == 'LKG':
                    return (1, 0)
                elif grade == 'UKG':
                    return (2, 0)
                elif grade.startswith('Grade '):
                    try:
                        grade_num = int(grade.replace('Grade ', ''))
                        return (3, grade_num)
                    except ValueError:
                        return (4, grade)
                else:
                    return (4, grade)

            # Sort grades in proper order
            selected_grades = sorted(all_grades, key=grade_sort_key)

            selected_grade = st.selectbox(
                "Filter by Grade:",
                ["All Grades"] + selected_grades,
                key="grade_filter_initial"
            )

        # Search by student name
        search_query = st.text_input(
            "🔍 Search by Student Name:",
            placeholder="Enter student name to search...",
            help="Search for specific students by name (case-insensitive)",
            key="student_search_initial"
        )

        st.markdown("---")

        # Apply filters
        filtered_results = initial_fee_results.copy()
        if selected_school != "All Schools":
            filtered_results = filtered_results[filtered_results['School'] == selected_school]
        if selected_status != "All":
            filtered_results = filtered_results[filtered_results['Status'] == selected_status]
        if selected_grade != "All Grades":
            filtered_results = filtered_results[filtered_results['Grade'] == selected_grade]

        # Apply search filter
        if search_query and search_query.strip():
            search_term = search_query.strip().lower()
            filtered_results = filtered_results[
                filtered_results['Student Name'].str.lower().str.contains(search_term, na=False)
            ]

        # Display the filtered results
        if not filtered_results.empty:
            # Format numeric columns for display
            display_df = filtered_results.copy()
            display_df['Opening Balance'] = display_df['Opening Balance'].apply(lambda x: f"₹{x:,.2f}" if x > 0 else "-")
            display_df['Total Paid Opening Balance'] = display_df['Total Paid Opening Balance'].apply(lambda x: f"₹{x:,.2f}" if x > 0 else "-")
            display_df['Remaining Opening Balance'] = display_df['Remaining Opening Balance'].apply(lambda x: f"₹{x:,.2f}" if x > 0 else "-")

            st.dataframe(
                display_df[['Customer ID', 'Student Name', 'School', 'Grade', 'Section', 'Status',
                           'Opening Balance', 'Total Paid Opening Balance', 'Remaining Opening Balance']],
                use_container_width=True,
                hide_index=True
            )

            st.info(f"Showing {len(display_df)} defaulters out of {len(initial_fee_results)} total")
        else:
            st.warning("No defaulters found matching the selected filters.")

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

        # Tabs for each school and payment analytics
        tab1, tab2, tab3 = st.tabs(["Excel Central School", "Excel Global School", "💰 Payment Analytics"])
        
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
        
        with tab3:
            # Payment Analytics Tab
            if st.session_state.payment_analytics and st.session_state.payment_analytics is not None:
                analytics = st.session_state.payment_analytics
                
                st.markdown("## 📊 Payment Collections Dashboard")
                st.info("ℹ️ **Note:** 'Paid' students include those with zero outstanding balance and those not yet invoiced.")
                st.markdown("---")
                
                # Overall metrics with accurate student counts
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric(
                        "💰 Total Collections", 
                        format_indian_currency(analytics['total_collected'])
                    )
                with col2:
                    ecs_total = analytics['school_totals'].get('Excel Central School', 0)
                    ecs_total_students = analytics['total_students_by_school'].get('Excel Central School', 0)
                    ecs_paid_students = analytics['students_paid_by_school'].get('Excel Central School', 0)
                    st.metric(
                        "🏫 ECS", 
                        format_indian_currency(ecs_total),
                        f"{ecs_paid_students}/{ecs_total_students} students"
                    )
                with col3:
                    egs_total = analytics['school_totals'].get('Excel Global School', 0)
                    egs_total_students = analytics['total_students_by_school'].get('Excel Global School', 0)
                    egs_paid_students = analytics['students_paid_by_school'].get('Excel Global School', 0)
                    st.metric(
                        "🏫 EGS", 
                        format_indian_currency(egs_total),
                        f"{egs_paid_students}/{egs_total_students} students"
                    )
                with col4:
                    # Total students who have paid across both schools
                    total_paid_students = sum(analytics['students_paid_by_school'].values())
                    total_all_students = sum(analytics['total_students_by_school'].values())
                    st.metric(
                        "📚 Overall",
                        f"{total_paid_students}/{total_all_students}",
                        f"{(total_paid_students/total_all_students*100):.1f}% paid"
                    )
                
                st.markdown("---")
                
                # Define proper grade order for charts
                grade_order = ['Pre-KG', 'LKG', 'UKG'] + [f'Grade {str(i).zfill(2)}' for i in range(1, 13)]
                
                # School-wise collection comparison
                st.subheader("📊 School-wise Collections")
                
                school_data = pd.DataFrame(list(analytics['school_totals'].items()), 
                                          columns=['School', 'Total Collections'])
                fig_school = px.bar(
                    school_data,
                    x='School',
                    y='Total Collections',
                    title='Total Collections by School',
                    color='School',
                    color_discrete_map={
                        'Excel Central School': '#FF6B6B',
                        'Excel Global School': '#4ECDC4'
                    },
                    text='Total Collections'
                )
                # Format text for Indian currency
                school_data['Formatted_Total'] = school_data['Total Collections'].apply(format_indian_currency)
                fig_school.update_traces(
                    text=school_data['Formatted_Total'],
                    texttemplate='%{text}',
                    textposition='outside'
                )
                fig_school.update_layout(
                    height=420,
                    showlegend=False,
                    yaxis_title='Amount (₹)'
                )
                st.plotly_chart(fig_school, use_container_width=True)
                
                # Grade-wise collections for each school
                st.subheader("🎓 Grade-wise Collections")
                
                # Tabs for each school's grade analysis
                school_tab1, school_tab2 = st.tabs(["Excel Central School", "Excel Global School"])
                
                with school_tab1:
                    ecs_grades = analytics['grade_payments'][
                        analytics['grade_payments']['School'] == 'Excel Central School'
                    ].copy()
                    
                    if not ecs_grades.empty:
                        # Sort by grade order
                        ecs_grades['Grade_Order'] = ecs_grades['Grade'].map({grade: i for i, grade in enumerate(grade_order)})
                        ecs_grades = ecs_grades.sort_values('Grade_Order')
                        
                        fig_ecs = px.bar(
                            ecs_grades,
                            x='Grade',
                            y='Total',
                            title='Collections by Grade - Excel Central School',
                            color='Total',
                            color_continuous_scale='Reds',
                            text='Total'
                        )
                        # Format text for Indian currency
                        ecs_grades['Formatted_Total'] = ecs_grades['Total'].apply(format_indian_currency)
                        fig_ecs.update_traces(
                            text=ecs_grades['Formatted_Total'],
                            texttemplate='%{text}',
                            textposition='outside'
                        )
                        fig_ecs.update_layout(
                            height=500,
                            xaxis_title='Grade',
                            yaxis_title='Amount (₹)',
                            showlegend=False
                        )
                        fig_ecs.update_xaxes(categoryorder='array', 
                                           categoryarray=[g for g in grade_order if g in ecs_grades['Grade'].values])
                        st.plotly_chart(fig_ecs, use_container_width=True)
                    else:
                        st.info("No collection data available for Excel Central School")
                
                with school_tab2:
                    egs_grades = analytics['grade_payments'][
                        analytics['grade_payments']['School'] == 'Excel Global School'
                    ].copy()
                    
                    if not egs_grades.empty:
                        # Sort by grade order
                        egs_grades['Grade_Order'] = egs_grades['Grade'].map({grade: i for i, grade in enumerate(grade_order)})
                        egs_grades = egs_grades.sort_values('Grade_Order')
                        
                        fig_egs = px.bar(
                            egs_grades,
                            x='Grade',
                            y='Total',
                            title='Collections by Grade - Excel Global School',
                            color='Total',
                            color_continuous_scale='teal',
                            text='Total'
                        )
                        # Format text for Indian currency
                        egs_grades['Formatted_Total'] = egs_grades['Total'].apply(format_indian_currency)
                        fig_egs.update_traces(
                            text=egs_grades['Formatted_Total'],
                            texttemplate='%{text}',
                            textposition='outside'
                        )
                        fig_egs.update_layout(
                            height=500,
                            xaxis_title='Grade',
                            yaxis_title='Amount (₹)',
                            showlegend=False
                        )
                        fig_egs.update_xaxes(categoryorder='array', 
                                           categoryarray=[g for g in grade_order if g in egs_grades['Grade'].values])
                        st.plotly_chart(fig_egs, use_container_width=True)
                    else:
                        st.info("No collection data available for Excel Global School")
                
                # Monthly collections trend (if data spans multiple months)
                if not analytics['monthly_payments'].empty:
                    st.subheader("📅 Monthly Collection Trends")
                    
                    monthly_data = analytics['monthly_payments'].copy()
                    # Convert Month back to datetime for proper sorting
                    monthly_data['Month_Date'] = pd.to_datetime(monthly_data['Month'], format='%B %Y')
                    monthly_data = monthly_data.sort_values('Month_Date')
                    
                    fig_monthly = px.line(
                        monthly_data,
                        x='Month',
                        y='Total',
                        color='School',
                        title='Monthly Collections Trend',
                        markers=True,
                        color_discrete_map={
                            'Excel Central School': '#FF6B6B',
                            'Excel Global School': '#4ECDC4'
                        }
                    )
                    # Create custom tick labels in Indian format
                    y_min = monthly_data['Total'].min()
                    y_max = monthly_data['Total'].max()
                    
                    # Generate tick values
                    import numpy as np
                    tick_vals = np.linspace(0, y_max * 1.1, 6)
                    tick_texts = [format_indian_currency(val) for val in tick_vals]
                    
                    fig_monthly.update_layout(
                        height=400,
                        xaxis_title='Month',
                        yaxis_title='Amount',
                        hovermode='x unified',
                        yaxis=dict(
                            tickmode='array',
                            tickvals=tick_vals,
                            ticktext=tick_texts
                        )
                    )
                    # Update hover template to show Indian currency format
                    for trace in fig_monthly.data:
                        school_data_hover = monthly_data[monthly_data['School'] == trace.name]
                        hover_texts = [format_indian_currency(val) for val in school_data_hover['Total']]
                        trace.hovertemplate = '%{x}<br>%{customdata}<extra></extra>'
                        trace.customdata = hover_texts
                    st.plotly_chart(fig_monthly, use_container_width=True)
                
                # Summary statistics
                st.subheader("📈 Collection Summary")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.info(f"**Total Paid Invoices:** {len(analytics['paid_invoices'])}")
                    total_without_inv = sum(analytics.get('students_without_invoices_by_school', {}).values())
                    total_fully_paid = len(analytics['fully_paid_students'])
                    actual_paid_with_inv = total_fully_paid - total_without_inv
                    st.info(f"**Fully Paid Students:** {total_fully_paid}\n- With invoices: {actual_paid_with_inv}\n- Not yet invoiced: {total_without_inv}")
                
                with col2:
                    st.info(f"**Highest Single Payment:** {format_indian_currency(analytics['paid_invoices']['Total'].max())}")
                    st.info(f"**Lowest Single Payment:** {format_indian_currency(analytics['paid_invoices']['Total'].min())}")
                
                # Payment Summary Table by Grade and Section
                st.subheader("📊 Payment Summary by Grade & Section")
                
                # Tabs for each school's payment summary
                summary_tab1, summary_tab2 = st.tabs(["Excel Central School", "Excel Global School"])
                
                with summary_tab1:
                    create_payment_summary_table('Excel Central School', analytics, st.session_state)
                
                with summary_tab2:
                    create_payment_summary_table('Excel Global School', analytics, st.session_state)
                    
            else:
                st.info("Payment analytics data will be available after processing the files.")

def create_payment_summary_table(school_name, analytics, session_state):
    """Create payment summary table for a school"""
    import pandas as pd
    
    # Get data for this school
    school_paid = analytics['students_paid_by_section'][
        analytics['students_paid_by_section']['School'] == school_name
    ].copy()
    
    # Load contacts data to get total students per section
    try:
        contacts_df = pd.read_csv('input/Contacts.csv')
        school_contacts = contacts_df[contacts_df['School'] == school_name].copy()
        
        # Get total students by grade and section
        total_by_section = school_contacts.groupby(['Grade', 'Section'])['Contact ID'].nunique().reset_index()
        total_by_section.columns = ['Grade', 'Section', 'Total_Students']
        
        # Merge with paid students data - use outer join to include all sections
        summary_data = pd.merge(
            total_by_section,
            school_paid[['Grade', 'Section', 'Students_Paid']],
            on=['Grade', 'Section'],
            how='left'
        ).fillna(0)
        
        summary_data['Students_Paid'] = summary_data['Students_Paid'].astype(int)
        summary_data['Total_Students'] = summary_data['Total_Students'].astype(int)
        
    except Exception as e:
        st.error(f"Error loading contacts data: {e}")
        return
    
    # Define grade order
    grade_order = ['Pre-KG', 'LKG', 'UKG'] + [f'Grade {str(i).zfill(2)}' for i in range(1, 13)]
    
    # Get unique sections for this school
    all_sections = sorted(summary_data['Section'].unique())
    
    # Create pivot table
    pivot_data = []
    grand_total_paid = 0
    grand_total_students = 0
    
    for grade in grade_order:
        if grade in summary_data['Grade'].values:
            grade_data = summary_data[summary_data['Grade'] == grade]
            row = {'Grade': grade}
            
            grade_total_paid = 0
            grade_total_students = 0
            
            for section in all_sections:
                section_data = grade_data[grade_data['Section'] == section]
                if not section_data.empty:
                    paid = int(section_data['Students_Paid'].values[0])
                    total = int(section_data['Total_Students'].values[0])
                    row[section] = f"{paid}/{total}"
                    grade_total_paid += paid
                    grade_total_students += total
                else:
                    row[section] = "0/0"
            
            row['Total'] = f"{grade_total_paid}/{grade_total_students}"
            grand_total_paid += grade_total_paid
            grand_total_students += grade_total_students
            pivot_data.append(row)
    
    # Add grand total row
    if pivot_data:
        grand_total_row = {'Grade': 'GRAND TOTAL'}
        for section in all_sections:
            section_total_paid = summary_data[summary_data['Section'] == section]['Students_Paid'].sum()
            section_total_students = summary_data[summary_data['Section'] == section]['Total_Students'].sum()
            grand_total_row[section] = f"{int(section_total_paid)}/{int(section_total_students)}"
        grand_total_row['Total'] = f"{grand_total_paid}/{grand_total_students}"
        pivot_data.append(grand_total_row)
    
    # Create DataFrame
    if pivot_data:
        display_df = pd.DataFrame(pivot_data)
        
        # Reorder columns: Grade, then sections, then Total
        cols = ['Grade'] + all_sections + ['Total']
        display_df = display_df[cols]
        
        # Style the dataframe
        def highlight_grand_total(row):
            if row['Grade'] == 'GRAND TOTAL':
                return ['background-color: #f0f2f6; font-weight: bold'] * len(row)
            return [''] * len(row)
        
        styled_df = display_df.style.apply(highlight_grand_total, axis=1)
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # Show summary metrics
        st.markdown(f"**Overall Payment Rate: {(grand_total_paid/grand_total_students*100):.1f}%** ({grand_total_paid} out of {grand_total_students} students)")

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