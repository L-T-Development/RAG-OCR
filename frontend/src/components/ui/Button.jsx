import './Button.css';

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  icon,
  iconOnly = false,
  loading = false,
  disabled = false,
  fullWidth = false,
  className = '',
  ...props
}) {
  const classes = [
    'btn',
    `btn--${variant}`,
    size !== 'md' && `btn--${size}`,
    iconOnly && 'btn--icon',
    loading && 'btn--loading',
    fullWidth && 'btn--full',
    className
  ].filter(Boolean).join(' ');

  return (
    <button
      className={classes}
      disabled={disabled || loading}
      {...props}
    >
      {icon && !loading && icon}
      {!iconOnly && children}
    </button>
  );
}

export default Button;
