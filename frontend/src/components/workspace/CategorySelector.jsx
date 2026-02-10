import { useState } from 'react';
import { FileText, Package, BookOpen, FolderOpen, FileCode, Pencil, Files } from 'lucide-react';
import './CategorySelector.css';

const CATEGORIES = [
  {
    value: 'mrls',
    label: 'MRLS',
    description: 'Maintenance Repair Level Schedule',
    icon: Package
  },
  {
    value: 'ispl',
    label: 'ISPL',
    description: 'Illustrated Spare Parts List',
    icon: Files
  },
  {
    value: 'manual',
    label: 'Manual',
    description: 'User/Technical Manual',
    icon: BookOpen
  },
  {
    value: 'catalog',
    label: 'Catalog',
    description: 'Parts Catalog',
    icon: FolderOpen
  },
  {
    value: 'specification',
    label: 'Specification',
    description: 'Technical Specs',
    icon: FileCode
  },
  {
    value: 'drawing',
    label: 'Drawing',
    description: 'Engineering Drawing',
    icon: Pencil
  },
  {
    value: 'other',
    label: 'Other',
    description: 'General Document',
    icon: FileText
  }
];

export function CategorySelector({ fileName, onSelect, onCancel }) {
  const [selectedCategory, setSelectedCategory] = useState('other');

  const handleSubmit = () => {
    onSelect(selectedCategory);
  };

  return (
    <div className="category-selector-overlay">
      <div className="category-selector-modal">
        <div className="category-selector-header">
          <h2>Choose Document Category</h2>
          <p className="category-selector-filename">
            <FileText size={16} />
            {fileName}
          </p>
        </div>

        <div className="category-selector-grid">
          {CATEGORIES.map(category => {
            const Icon = category.icon;
            return (
              <button
                key={category.value}
                className={`category-card ${selectedCategory === category.value ? 'category-card--selected' : ''}`}
                onClick={() => setSelectedCategory(category.value)}
              >
                <div className="category-card-icon">
                  <Icon size={24} />
                </div>
                <div className="category-card-content">
                  <div className="category-card-label">{category.label}</div>
                  <div className="category-card-description">{category.description}</div>
                </div>
                <div className="category-card-radio">
                  <input
                    type="radio"
                    checked={selectedCategory === category.value}
                    onChange={() => setSelectedCategory(category.value)}
                  />
                </div>
              </button>
            );
          })}
        </div>

        <div className="category-selector-footer">
          <button className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn-confirm" onClick={handleSubmit}>
            Upload Document
          </button>
        </div>
      </div>
    </div>
  );
}
