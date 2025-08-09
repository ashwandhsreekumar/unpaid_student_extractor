# Fee Defaulter Extraction System

A comprehensive solution for K-12 schools to identify and manage fee defaulters from Zoho Books data.

## Features

- **Multi-School Support**: Handles both Excel Global School (term-based fees) and Excel Central School (monthly fees)
- **Dynamic Date-Based Columns**: Automatically shows only fees due up to the current date
- **Dual Report Types**:
  - **Teacher Reports**: Simple Paid/Unpaid status for class teachers
  - **Accounts Reports**: Detailed outstanding amounts for finance team
- **Interactive Dashboard**: Streamlit-based web interface with visualizations
- **Automated Organization**: Reports organized by School → Grade → Section

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd unpaid_student_extractor
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Command Line Interface

Run the extraction script directly:

```bash
python fee_extractor.py
```

This will:
- Read CSV files from the `input/` folder
- Process overdue and partially paid invoices
- Generate reports in `output/teachers/` and `output/accounts/`

### Streamlit Web Application

Launch the interactive web application:

```bash
streamlit run app.py
```

Then:
1. Open your browser to `http://localhost:8501`
2. Upload Contacts.csv and Invoice.csv files
3. Click "Process Files"
4. View analytics and download reports

## Input File Structure

### Contacts.csv
Required columns:
- Customer ID
- First Name
- Last Name
- School
- Grade
- Section
- CF.Admission No / Reference code

### Invoice.csv
Required columns:
- Customer ID
- Customer Name
- Invoice Status
- Due Date
- School
- Grade
- Section
- Item Name
- Balance

## Output Structure

```
output/
├── teachers/
│   ├── Excel Global School/
│   │   ├── Pre-KG/
│   │   │   └── Blue.csv
│   │   ├── LKG/
│   │   │   ├── Blue.csv
│   │   │   └── Green.csv
│   │   └── [other grades]/
│   └── Excel Central School/
│       └── [grades]/[sections].csv
└── accounts/
    └── [same structure as teachers]
```

### Teacher Report Format
| Student Name | Admission No | Grade | Section | Initial Fee | Term I/Jun-2025 | ... |
|--------------|--------------|-------|---------|-------------|-----------------|-----|
| John Doe     | 001          | LKG   | Blue    | Paid        | Unpaid          | ... |

### Accounts Report Format
| Student Name | Admission No | Grade | Section | Initial Fee | Term I/Jun-2025 | ... | Total Outstanding |
|--------------|--------------|-------|---------|-------------|-----------------|-----|-------------------|
| John Doe     | 001          | LKG   | Blue    | 0           | 15000           | ... | 15000             |

## Fee Structure

### Excel Global School
- Initial Academic Fee
- Term I Fee (June)
- Term II Fee (September)
- Term III Fee (January)

### Excel Central School
- Initial Academic Fee
- Monthly Fees (June 2025 - March 2026)

## Dynamic Date Handling

The system automatically determines which fee columns to display based on the current date:

- **August 2025**: Shows Initial Fee, Term I, Jun-2025, Jul-2025, Aug-2025
- **December 2025**: Adds Term II and monthly fees through Dec-2025
- **February 2026**: Adds Term III and monthly fees through Feb-2026

## Cloud Deployment

### Streamlit Cloud

1. Push code to GitHub
2. Connect repository to Streamlit Cloud
3. Deploy with environment variables if needed

### Docker Deployment

Create a `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

Build and run:
```bash
docker build -t fee-extractor .
docker run -p 8501:8501 fee-extractor
```

## Troubleshooting

### Common Issues

1. **File encoding errors**: Ensure CSV files are saved in UTF-8 encoding
2. **Missing columns**: Verify all required columns are present in input files
3. **Date parsing**: Check date formats in Invoice.csv (should be YYYY-MM-DD)

### Data Quality

- The system handles missing sections by labeling them as "General"
- Partially paid invoices are only considered overdue if past the due date
- Empty grades or sections are handled gracefully

## License

MIT License

## Support

For issues or questions, please contact the development team.