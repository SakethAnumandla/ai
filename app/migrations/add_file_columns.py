# migrations/add_file_columns.py
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add file storage columns to expenses table
    op.add_column('expenses', sa.Column('file_data', sa.LargeBinary(), nullable=True))
    op.add_column('expenses', sa.Column('file_hash', sa.String(64), nullable=True))
    op.add_column('expenses', sa.Column('thumbnail_data', sa.LargeBinary(), nullable=True))
    
    # Add indexes for file_hash for deduplication
    op.create_index('ix_expenses_file_hash', 'expenses', ['file_hash'])
    
    # Add file storage columns to ocr_bills table
    op.add_column('ocr_bills', sa.Column('original_file_data', sa.LargeBinary(), nullable=True))
    op.add_column('ocr_bills', sa.Column('original_file_name', sa.String(), nullable=True))
    op.add_column('ocr_bills', sa.Column('original_file_size', sa.Integer(), nullable=True))
    op.add_column('ocr_bills', sa.Column('original_mime_type', sa.String(), nullable=True))

def downgrade():
    # Remove columns
    op.drop_column('expenses', 'thumbnail_data')
    op.drop_column('expenses', 'file_hash')
    op.drop_column('expenses', 'file_data')
    op.drop_index('ix_expenses_file_hash', 'expenses')
    
    op.drop_column('ocr_bills', 'original_mime_type')
    op.drop_column('ocr_bills', 'original_file_size')
    op.drop_column('ocr_bills', 'original_file_name')
    op.drop_column('ocr_bills', 'original_file_data')