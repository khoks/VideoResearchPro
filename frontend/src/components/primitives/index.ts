/*
 * Primitive components for Pratidhvani's warm-editorial UI.
 *
 * Every inline style in the app should compose one of these — or, if you need a
 * new primitive, add it here first and document it in docs/ui-design.md §3.
 */

export { Button, type ButtonProps, type ButtonSize, type ButtonVariant } from './Button';
export { Card, type CardProps } from './Card';
export { Input, Textarea, Select, type InputProps, type TextareaProps, type SelectProps } from './Input';
export { FormField, type FormFieldProps } from './FormField';
export { Badge, StatusPill, type BadgeProps, type BadgeSize, type BadgeTone } from './Badge';
export { Modal, type ModalProps } from './Modal';
export { Spinner, Skeleton, type SpinnerProps, type SkeletonProps } from './Spinner';
export { EmptyState, type EmptyStateProps } from './EmptyState';
