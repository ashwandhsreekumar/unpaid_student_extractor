import pandas as pd
from pathlib import Path
from fee_extractor import FeeDefaulterExtractor

class InitialFeeDefaulterExtractor:
    def __init__(self, contacts_path, invoices_path, payments_path, output_base_path):
        """
        Initialize the Initial Fee Defaulter Extractor

        Args:
            contacts_path: Path to Contacts.csv
            invoices_path: Path to Invoice.csv
            payments_path: Path to Customer_Payment.csv
            output_base_path: Base path for output folders
        """
        self.contacts_path = contacts_path
        self.invoices_path = invoices_path
        self.payments_path = payments_path
        self.output_base_path = output_base_path
        self.today = pd.Timestamp.now().date()

    def load_customer_payments(self):
        """Load and process customer payment data"""
        print("Loading customer payment data...")
        try:
            payments_df = pd.read_csv(self.payments_path)

            # Filter for opening balance payments
            opening_balance_payments = payments_df[
                payments_df['Invoice Number'] == 'Customer opening balance'
            ].copy()

            # Convert amount to numeric
            opening_balance_payments['Amount Applied to Invoice'] = pd.to_numeric(
                opening_balance_payments['Amount Applied to Invoice'], errors='coerce'
            )

            # Group by CustomerID and sum payments
            self.opening_balance_payments = opening_balance_payments.groupby('CustomerID').agg({
                'Amount Applied to Invoice': 'sum',
                'Customer Name': 'first'
            }).reset_index()

            self.opening_balance_payments.rename(columns={
                'Amount Applied to Invoice': 'Total Paid Opening Balance'
            }, inplace=True)

            print(f"Found {len(self.opening_balance_payments)} customers with opening balance payments")
            return True

        except Exception as e:
            print(f"Error loading customer payments: {e}")
            return False

    def load_contacts_with_opening_balance(self):
        """Load contacts data and filter for students with opening balances"""
        print("Loading contacts with opening balance data...")
        try:
            contacts_df = pd.read_csv(self.contacts_path)

            # Convert opening balance to numeric
            contacts_df['Opening Balance'] = pd.to_numeric(
                contacts_df['Opening Balance'], errors='coerce'
            )

            # Filter for students with opening balance > 0
            contacts_with_balance = contacts_df[
                contacts_df['Opening Balance'] > 0
            ].copy()

            # Select relevant columns
            self.contacts_balance_df = contacts_with_balance[[
                'Contact ID', 'First Name', 'Last Name', 'School', 'Grade', 'Section', 'Opening Balance'
            ]].copy()

            # Create full student name
            self.contacts_balance_df['Student Name'] = self.contacts_balance_df['First Name'] + ' ' + self.contacts_balance_df['Last Name']

            print(f"Found {len(self.contacts_balance_df)} students with opening balances")
            return True

        except Exception as e:
            print(f"Error loading contacts: {e}")
            return False

    def identify_opening_balance_defaulters(self):
        """Identify students who haven't fully paid their opening balances"""
        print("Identifying opening balance defaulters...")

        if not hasattr(self, 'contacts_balance_df') or not hasattr(self, 'opening_balance_payments'):
            print("Required data not loaded")
            return pd.DataFrame()

        # Merge contacts with payments
        merged_df = self.contacts_balance_df.merge(
            self.opening_balance_payments,
            left_on='Contact ID',
            right_on='CustomerID',
            how='left'
        )

        # Fill NaN values with 0 for unpaid amounts
        merged_df['Total Paid Opening Balance'] = merged_df['Total Paid Opening Balance'].fillna(0)

        # Calculate remaining balance
        merged_df['Remaining Opening Balance'] = merged_df['Opening Balance'] - merged_df['Total Paid Opening Balance']

        # Filter for students with remaining balance > 0
        opening_balance_defaulters = merged_df[
            merged_df['Remaining Opening Balance'] > 0
        ].copy()

        # Format the defaulters data
        opening_balance_defaulters = opening_balance_defaulters[[
            'Contact ID', 'Student Name', 'School', 'Grade', 'Section',
            'Opening Balance', 'Total Paid Opening Balance', 'Remaining Opening Balance'
        ]]

        opening_balance_defaulters['Status'] = 'Opening Balance Not Fully Paid'
        opening_balance_defaulters['Section'] = opening_balance_defaulters['Section'].fillna('-')

        print(f"Found {len(opening_balance_defaulters)} students with unpaid opening balances")
        return opening_balance_defaulters

    def extract_initial_fee_defaulters(self):
        """Extract students who haven't paid their initial fee or opening balance"""
        print("Starting Fee and Opening Balance Defaulter Extraction...")
        print("=" * 70)

        # Load opening balance data first
        if not self.load_customer_payments():
            print("Failed to load customer payment data")
            return pd.DataFrame()

        if not self.load_contacts_with_opening_balance():
            print("Failed to load contacts data")
            return pd.DataFrame()

        # Get opening balance defaulters
        opening_balance_defaulters = self.identify_opening_balance_defaulters()

        # Use the existing FeeDefaulterExtractor to load and process data
        extractor = FeeDefaulterExtractor(
            contacts_path=self.contacts_path,
            invoices_path=self.invoices_path,
            output_base_path=self.output_base_path
        )

        # Load data using existing functionality
        extractor.load_data()

        # Process invoices using existing functionality
        defaulter_invoices = extractor.process_invoices()

        # Collect all initial fee defaulters
        all_defaulters = []

        # Process each school
        schools = ['Excel Global School', 'Excel Central School']

        for school in schools:
            print(f"\nProcessing {school}...")

            # Filter for specific school
            school_invoices = defaulter_invoices[
                defaulter_invoices['School'] == school
            ].copy()

            if len(school_invoices) == 0:
                print(f"No defaulters found for {school}")
                continue

            # Extract fee type using existing method
            school_invoices['Fee Type'] = school_invoices['Item Name'].apply(
                lambda x: extractor.extract_fee_type(x, school)
            )

            # Filter for initial fee defaulters only
            initial_fee_defaulters = school_invoices[
                school_invoices['Fee Type'] == 'Initial Fee'
            ].copy()

            if len(initial_fee_defaulters) == 0:
                print(f"No initial fee defaulters found for {school}")
                continue

            # Get unique defaulter customer IDs
            defaulter_ids = initial_fee_defaulters['Customer ID'].unique()

            # Get ALL invoices for these defaulters to check complete payment status
            all_invoices_for_defaulters = extractor.invoices_df[
                (extractor.invoices_df['Customer ID'].isin(defaulter_ids)) &
                (extractor.invoices_df['School'] == school)
            ].copy()

            all_invoices_for_defaulters['Fee Type'] = all_invoices_for_defaulters['Item Name'].apply(
                lambda x: extractor.extract_fee_type(x, school)
            )

            # Group by student and grade/section
            initial_fee_defaulters['Section'] = initial_fee_defaulters['Section'].fillna('-')

            for (customer_id, grade, section), group in initial_fee_defaulters.groupby(
                ['Customer ID', 'Grade', 'Section']
            ):
                # Check if initial fee is actually unpaid
                student_all_invoices = all_invoices_for_defaulters[
                    all_invoices_for_defaulters['Customer ID'] == customer_id
                ]

                # Check initial fee status
                initial_fee_invoices = student_all_invoices[
                    student_all_invoices['Fee Type'] == 'Initial Fee'
                ]

                if len(initial_fee_invoices) > 0:
                    # Check if fee is paid
                    has_closed = any(initial_fee_invoices['Invoice Status'].isin(['Closed', 'Paid']))

                    if not has_closed:
                        # Student has initial fee that is not paid
                        defaulter_data = {
                            'Customer ID': customer_id,
                            'Student Name': group['Student Name'].iloc[0],
                            'School': school,
                            'Grade': grade,
                            'Section': section if pd.notna(section) else '-',
                            'Status': 'Initial Fee Not Paid',
                            'Opening Balance': 0.00,
                            'Total Paid Opening Balance': 0.00,
                            'Remaining Opening Balance': 0.00
                        }
                        all_defaulters.append(defaulter_data)

            print(f"Found {len(initial_fee_defaulters['Customer ID'].unique())} initial fee defaulters in {school}")

        # Merge with opening balance defaulters
        if not opening_balance_defaulters.empty:
            # Format opening balance defaulters to match the structure
            formatted_opening_balance_defaulters = []
            for _, row in opening_balance_defaulters.iterrows():
                formatted_data = {
                    'Customer ID': row['Contact ID'],
                    'Student Name': row['Student Name'],
                    'School': row['School'],
                    'Grade': row['Grade'],
                    'Section': row['Section'],
                    'Status': row['Status'],
                    'Opening Balance': row['Opening Balance'],
                    'Total Paid Opening Balance': row['Total Paid Opening Balance'],
                    'Remaining Opening Balance': row['Remaining Opening Balance']
                }
                formatted_opening_balance_defaulters.append(formatted_data)

            all_defaulters.extend(formatted_opening_balance_defaulters)
            print(f"\nAdded {len(formatted_opening_balance_defaulters)} opening balance defaulters")

        # Create DataFrame from all defaulters
        if all_defaulters:
            defaulters_df = pd.DataFrame(all_defaulters)

            # Remove duplicates (students who have both unpaid fees and opening balance)
            defaulters_df = defaulters_df.drop_duplicates(subset=['Customer ID'], keep='first')

            defaulters_df = defaulters_df.sort_values(['School', 'Grade', 'Section', 'Student Name'])
            print(f"\nTotal defaulters found: {len(defaulters_df)}")
            print(f"- Initial fee defaulters: {len(defaulters_df[defaulters_df['Status'] == 'Initial Fee Not Paid'])}")
            print(f"- Opening balance defaulters: {len(defaulters_df[defaulters_df['Status'] == 'Opening Balance Not Fully Paid'])}")
            return defaulters_df
        else:
            print("\nNo defaulters found")
            return pd.DataFrame()

    def save_defaulters_report(self, defaulters_df):
        """Save the fee and opening balance defaulters report"""
        if defaulters_df.empty:
            print("No data to save")
            return

        # Create output directory if it doesn't exist
        output_path = Path(self.output_base_path)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save to CSV with better formatting
        output_file = output_path / 'fee_and_opening_balance_defaulters.csv'

        # Format numeric columns
        defaulters_df_copy = defaulters_df.copy()
        numeric_cols = ['Opening Balance', 'Total Paid Opening Balance', 'Remaining Opening Balance']
        for col in numeric_cols:
            if col in defaulters_df_copy.columns:
                defaulters_df_copy[col] = defaulters_df_copy[col].round(2)

        defaulters_df_copy.to_csv(output_file, index=False)

        print(f"Report saved to: {output_file}")
        print(f"Total records: {len(defaulters_df_copy)}")

        # Print summary
        fee_defaulters = len(defaulters_df_copy[defaulters_df_copy['Status'] == 'Initial Fee Not Paid'])
        opening_balance_defaulters = len(defaulters_df_copy[defaulters_df_copy['Status'] == 'Opening Balance Not Fully Paid'])
        print(f"- Initial fee defaulters: {fee_defaulters}")
        print(f"- Opening balance defaulters: {opening_balance_defaulters}")

        # Calculate total outstanding amounts for opening balance defaulters
        if opening_balance_defaulters > 0:
            total_outstanding = defaulters_df_copy[
                defaulters_df_copy['Status'] == 'Opening Balance Not Fully Paid'
            ]['Remaining Opening Balance'].sum()
            print(f"- Total outstanding opening balance: ₹{total_outstanding:,.2f}")

    def run(self):
        """Main execution method"""
        defaulters_df = self.extract_initial_fee_defaulters()
        if not defaulters_df.empty:
            self.save_defaulters_report(defaulters_df)
        print("\n" + "=" * 70)
        print("Fee and Opening Balance Defaulter Extraction Complete!")
        return True

def main():
    """Main function to run the initial fee defaulter extractor"""
    base_path = Path(__file__).parent

    extractor = InitialFeeDefaulterExtractor(
        contacts_path=base_path / 'input' / 'Contacts.csv',
        invoices_path=base_path / 'input' / 'Invoice.csv',
        payments_path=base_path / 'input' / 'Customer_Payment.csv',
        output_base_path=base_path / 'output'
    )

    extractor.run()

if __name__ == "__main__":
    main()
