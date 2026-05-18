import { useState } from 'react';
import { FileText, Package, BookOpen, FolderOpen, FileCode, Pencil, Files } from 'lucide-react';

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
      <div className="w-full max-w-lg rounded-2xl bg-[var(--color-bg-primary)] border border-[var(--color-border)] shadow-[var(--shadow-lg)] flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-[var(--color-border)]">
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] m-0">
            Choose Document Category
          </h2>
          <p className="flex items-center gap-1.5 mt-2 mb-0 text-sm text-[var(--color-text-muted)]">
            <FileText size={16} />
            {fileName}
          </p>
        </div>

        {/* Category grid */}
        <div className="overflow-y-auto flex-1 p-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {CATEGORIES.map(category => {
              const Icon = category.icon;
              const isSelected = selectedCategory === category.value;
              return (
                <button
                  key={category.value}
                  className={`flex flex-col items-start gap-2 p-3 rounded-xl border-2 text-left cursor-pointer transition-all
                    ${isSelected
                      ? 'border-primary bg-primary-light'
                      : 'border-[var(--color-border)] bg-[var(--color-bg-secondary)] hover:border-[var(--color-border-focus)] hover:bg-[var(--color-bg-hover)]'
                    }`}
                  onClick={() => setSelectedCategory(category.value)}
                >
                  <div
                    className={`flex items-center justify-center w-9 h-9 rounded-lg
                      ${isSelected ? 'bg-primary text-white' : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]'}`}
                  >
                    <Icon size={24} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm font-semibold ${isSelected ? 'text-primary' : 'text-[var(--color-text-primary)]'}`}>
                      {category.label}
                    </div>
                    <div className="text-xs text-[var(--color-text-muted)] leading-tight mt-0.5">
                      {category.description}
                    </div>
                  </div>
                  <input
                    type="radio"
                    className="sr-only"
                    checked={isSelected}
                    onChange={() => setSelectedCategory(category.value)}
                  />
                </button>
              );
            })}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer bg-transparent"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="px-4 py-2 rounded-lg text-sm font-medium bg-primary hover:bg-primary-hover text-white transition-colors cursor-pointer border-0"
            onClick={handleSubmit}
          >
            Upload Document
          </button>
        </div>
      </div>
    </div>
  );
}
