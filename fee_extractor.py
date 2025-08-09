import pandas as pd
import numpy as np
from datetime import datetime, date
import os
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

class FeeDefaulterExtractor:
    def __init__(self, contacts_path, invoices_path, output_base_path):
        """
        Initialize the Fee Defaulter Extractor
        
        Args:
            contacts_path: Path to Contacts.csv
            invoices_path: Path to Invoice.csv
            output_base_path: Base path for output folders
        """
        self.contacts_path = contacts_path
        self.invoices_path = invoices_path
        self.output_base_path = output_base_path
        self.today = date.today()
        
        # Define fee structures for each school
        self.excel_global_fees = {
            'Initial Academic Fee': 'Initial Fee',
            'Term I Fee (June)': 'Term I',
            'Term II Fee (Sept)': 'Term II',
            'Term III Fee (Jan)': 'Term III'
        }
        
        self.excel_central_months = [
            'June', 'July', 'August', 'September', 'October',
            'November', 'December', 'January', 'February', 'March'
        ]
        
    def load_data(self):
        """Load contacts and invoices data"""
        print("Loading data files...")
        self.contacts_df = pd.read_csv(self.contacts_path)
        self.invoices_df = pd.read_csv(self.invoices_path)
        print(f"Loaded {len(self.contacts_df)} contacts and {len(self.invoices_df)} invoices")
        
    def get_due_fees_columns(self, school, overdue_fee_types=None):
        """
        Get the fee columns that should be due by today's date or have overdue invoices
        
        Args:
            school: School name (Excel Global School or Excel Central School)
            overdue_fee_types: Set of fee types that have overdue invoices
            
        Returns:
            List of column names for fees due
        """
        columns = ['Initial Fee']
        
        if school == 'Excel Global School':
            # Term-based fees - show if date reached OR if overdue invoices exist
            if self.today >= date(2025, 6, 1) or (overdue_fee_types and 'Term I' in overdue_fee_types):
                columns.append('Term I')
            if self.today >= date(2025, 9, 1) or (overdue_fee_types and 'Term II' in overdue_fee_types):
                columns.append('Term II')
            if self.today >= date(2026, 1, 1) or (overdue_fee_types and 'Term III' in overdue_fee_types):
                columns.append('Term III')
                
        elif school == 'Excel Central School':
            # Monthly fees
            year = 2025
            month_mapping = {
                'June': (6, 2025), 'July': (7, 2025), 'August': (8, 2025),
                'September': (9, 2025), 'October': (10, 2025), 'November': (11, 2025),
                'December': (12, 2025), 'January': (1, 2026), 'February': (2, 2026),
                'March': (3, 2026)
            }
            
            for month_name in self.excel_central_months:
                month_num, year = month_mapping[month_name]
                if self.today >= date(year, month_num, 1):
                    columns.append(f"{month_name[:3]}-{year}")
                else:
                    break
                    
        return columns
    
    def process_invoices(self):
        """Process invoices to identify defaulters"""
        print("Processing invoices...")
        
        # Filter for overdue and partially paid invoices
        defaulter_invoices = self.invoices_df[
            (self.invoices_df['Invoice Status'].isin(['Overdue', 'PartiallyPaid']))
        ].copy()
        
        # For PartiallyPaid, check if past due date
        if 'Due Date' in defaulter_invoices.columns:
            defaulter_invoices['Due Date'] = pd.to_datetime(defaulter_invoices['Due Date'], errors='coerce')
            today_datetime = pd.Timestamp(self.today)
            
            # Keep only PartiallyPaid that are past due date
            partially_paid_mask = defaulter_invoices['Invoice Status'] == 'PartiallyPaid'
            past_due_mask = defaulter_invoices['Due Date'] < today_datetime
            
            defaulter_invoices = defaulter_invoices[
                (defaulter_invoices['Invoice Status'] == 'Overdue') |
                (partially_paid_mask & past_due_mask)
            ]
        
        print(f"Found {len(defaulter_invoices)} overdue invoice entries")
        
        # Merge with contacts to get student details
        defaulter_invoices = defaulter_invoices.merge(
            self.contacts_df[['Contact ID', 'First Name', 'Last Name', 'CF.Enrollment Code']],
            left_on='Customer ID',
            right_on='Contact ID',
            how='left'
        )
        
        # Clean up student name
        defaulter_invoices['Student Name'] = (
            defaulter_invoices['First Name'].fillna('') + ' ' + 
            defaulter_invoices['Last Name'].fillna('')
        ).str.strip()
        
        defaulter_invoices['Enrollment No'] = defaulter_invoices['CF.Enrollment Code'].fillna('')
        
        return defaulter_invoices
    
    def extract_fee_type(self, item_name, school):
        """Extract fee type from item name"""
        if pd.isna(item_name):
            return None
            
        item_name = str(item_name)
        
        if school == 'Excel Global School':
            for key, value in self.excel_global_fees.items():
                if key in item_name:
                    return value
        elif school == 'Excel Central School':
            if 'Initial Academic Fee' in item_name:
                return 'Initial Fee'
            else:
                # Extract month from item name
                for month in self.excel_central_months:
                    if f"{month} Monthly Fee" in item_name:
                        year = 2026 if month in ['January', 'February', 'March'] else 2025
                        return f"{month[:3]}-{year}"
        return None
    
    def create_student_summary(self, defaulter_invoices, school):
        """Create summary of defaulters by student"""
        print(f"Creating summary for {school}...")
        
        # Filter for specific school
        school_invoices = defaulter_invoices[
            defaulter_invoices['School'] == school
        ].copy()
        
        if len(school_invoices) == 0:
            print(f"No defaulters found for {school}")
            return pd.DataFrame()
        
        # Extract fee type
        school_invoices['Fee Type'] = school_invoices['Item Name'].apply(
            lambda x: self.extract_fee_type(x, school)
        )
        
        # Get unique fee types that have overdue invoices
        overdue_fee_types = set(school_invoices['Fee Type'].dropna().unique())
        
        # Get due fee columns for this school, including those with overdue invoices
        due_columns = self.get_due_fees_columns(school, overdue_fee_types)
        
        # Get list of defaulter customer IDs
        defaulter_ids = school_invoices['Customer ID'].unique()
        
        # Now get ALL invoices for these defaulters to check complete payment status
        all_invoices_for_defaulters = self.invoices_df[
            (self.invoices_df['Customer ID'].isin(defaulter_ids)) &
            (self.invoices_df['School'] == school)
        ].copy()
        
        all_invoices_for_defaulters['Fee Type'] = all_invoices_for_defaulters['Item Name'].apply(
            lambda x: self.extract_fee_type(x, school)
        )
        
        # Group by student and grade/section
        grouped = []
        for (customer_id, grade, section), group in school_invoices.groupby(
            ['Customer ID', 'Grade', 'Section']
        ):
            student_data = {
                'Customer ID': customer_id,
                'Student Name': group['Student Name'].iloc[0],
                'Enrollment No': group['Enrollment No'].iloc[0],
                'Grade': grade,
                'Section': section if pd.notna(section) else 'General'
            }
            
            # Get all invoices for this student
            student_all_invoices = all_invoices_for_defaulters[
                all_invoices_for_defaulters['Customer ID'] == customer_id
            ]
            
            # For each fee column, check payment status
            for col in due_columns:
                # Check overdue invoices for this fee type
                overdue_amount = group[group['Fee Type'] == col]['Balance'].sum()
                
                # Check if there are ANY invoices (paid or unpaid) for this fee type
                all_fee_invoices = student_all_invoices[student_all_invoices['Fee Type'] == col]
                
                if len(all_fee_invoices) > 0:
                    # Check if all invoices for this fee are paid (Balance = 0 or Status = Closed/Paid)
                    total_balance = all_fee_invoices['Balance'].sum()
                    has_closed = any(all_fee_invoices['Invoice Status'].isin(['Closed', 'Paid']))
                    
                    if overdue_amount > 0:
                        # Has overdue amount
                        student_data[col] = overdue_amount
                    elif has_closed or total_balance == 0:
                        # Fee has been paid
                        student_data[col] = -1  # Use -1 to indicate paid
                    else:
                        # Has invoice but not overdue (future due date)
                        student_data[col] = 0
                else:
                    # No invoice for this fee type
                    student_data[col] = 0
            
            # Calculate total outstanding (only positive amounts, exclude -1 which means paid)
            student_data['Total Outstanding'] = sum(
                max(0, student_data[col]) for col in due_columns
            )
            
            grouped.append(student_data)
        
        return pd.DataFrame(grouped)
    
    def create_teacher_report(self, summary_df, due_columns):
        """Create teacher report with Paid/Unpaid status"""
        teacher_df = summary_df[['Student Name', 'Enrollment No', 'Grade', 'Section']].copy()
        
        for col in due_columns:
            if col in summary_df.columns:
                # -1 means paid, positive means unpaid, 0 means no invoice or not due
                teacher_df[col] = summary_df[col].apply(
                    lambda x: 'Unpaid' if x > 0 else ('Paid' if x == -1 else '')
                )
        
        return teacher_df
    
    def create_accounts_report(self, summary_df):
        """Create accounts report with amounts"""
        accounts_df = summary_df.copy()
        
        # Replace -1 (paid indicator) with 0 for accounts report
        fee_columns = [col for col in accounts_df.columns 
                      if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                     'Grade', 'Section', 'Total Outstanding']]
        
        for col in fee_columns:
            if col in accounts_df.columns:
                accounts_df[col] = accounts_df[col].apply(lambda x: 0 if x == -1 else x)
        
        return accounts_df
    
    def save_reports(self, summary_df, school):
        """Save reports to appropriate folders"""
        if summary_df.empty:
            return
            
        print(f"Saving reports for {school}...")
        
        # Get due columns based on what's actually in the summary
        # (which already includes overdue fee types)
        due_columns = [col for col in summary_df.columns 
                      if col not in ['Customer ID', 'Student Name', 'Enrollment No', 
                                     'Grade', 'Section', 'Total Outstanding']]
        
        # Group by grade and section
        for (grade, section), group_df in summary_df.groupby(['Grade', 'Section']):
            # Clean grade and section names for folder/file names
            grade_clean = str(grade).replace('/', '_').strip()
            section_clean = str(section).replace('/', '_').strip() if pd.notna(section) else 'General'
            
            # Create descriptive filename
            school_prefix = 'EGS' if school == 'Excel Global School' else 'ECS'
            filename = f"{school_prefix} {grade_clean} {section_clean}.csv"
            
            # Create teacher report
            teacher_report = self.create_teacher_report(group_df, due_columns)
            teacher_report = teacher_report.sort_values('Student Name')
            
            # Create accounts report
            accounts_report = self.create_accounts_report(group_df)
            accounts_report = accounts_report.sort_values('Student Name')
            
            # Save teacher report
            teacher_path = Path(self.output_base_path) / 'teachers' / school / grade_clean
            teacher_path.mkdir(parents=True, exist_ok=True)
            teacher_file = teacher_path / filename
            teacher_report.to_csv(teacher_file, index=False)
            
            # Save accounts report
            accounts_path = Path(self.output_base_path) / 'accounts' / school / grade_clean
            accounts_path.mkdir(parents=True, exist_ok=True)
            accounts_file = accounts_path / filename
            accounts_report.to_csv(accounts_file, index=False)
            
            print(f"  Saved {grade_clean}/{section_clean}: {len(group_df)} students")
    
    def run(self):
        """Main execution method"""
        print(f"Starting Fee Defaulter Extraction - Date: {self.today}")
        print("=" * 60)
        
        # Load data
        self.load_data()
        
        # Process invoices
        defaulter_invoices = self.process_invoices()
        
        # Process each school
        schools = ['Excel Global School', 'Excel Central School']
        
        for school in schools:
            print(f"\nProcessing {school}...")
            summary_df = self.create_student_summary(defaulter_invoices, school)
            
            if not summary_df.empty:
                self.save_reports(summary_df, school)
                print(f"Total defaulters in {school}: {len(summary_df)}")
            else:
                print(f"No defaulters found in {school}")
        
        print("\n" + "=" * 60)
        print("Extraction complete!")
        
        return True

def main():
    """Main function to run the extractor"""
    base_path = '/Users/digital-synapses/code/accounts/unpaid_student_extractor'
    
    extractor = FeeDefaulterExtractor(
        contacts_path=f'{base_path}/input/Contacts.csv',
        invoices_path=f'{base_path}/input/Invoice.csv',
        output_base_path=f'{base_path}/output'
    )
    
    extractor.run()

if __name__ == "__main__":
    main()