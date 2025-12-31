import './Input.css';

export function Input({
  label,
  error,
  icon,
  size = 'md',
  className = '',
  ...props
}) {
  const inputClasses = [
    'input',
    size !== 'md' && `input--${size}`,
    error && 'input--error',
    className
  ].filter(Boolean).join(' ');

  const input = (
    <input className={inputClasses} {...props} />
  );

  if (!label && !icon && !error) return input;

  return (
    <div className="input-wrapper">
      {label && <label className="input-label">{label}</label>}
      {icon ? (
        <div className="input-icon-wrapper">
          <span className="input-icon">{icon}</span>
          {input}
        </div>
      ) : input}
      {error && <span className="input-error-message">{error}</span>}
    </div>
  );
}

export function Textarea({
  label,
  error,
  className = '',
  ...props
}) {
  const classes = [
    'input',
    'input--textarea',
    error && 'input--error',
    className
  ].filter(Boolean).join(' ');

  return (
    <div className="input-wrapper">
      {label && <label className="input-label">{label}</label>}
      <textarea className={classes} {...props} />
      {error && <span className="input-error-message">{error}</span>}
    </div>
  );
}

export default Input;
