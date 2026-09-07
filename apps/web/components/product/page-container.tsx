import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react';

import { cn } from '@/lib/utils';

type PageContainerProps<T extends ElementType = 'div'> = {
  as?: T;
  children: ReactNode;
  className?: string;
} & Omit<ComponentPropsWithoutRef<T>, 'as' | 'children' | 'className'>;

export function PageContainer<T extends ElementType = 'div'>({
  as,
  children,
  className,
  ...props
}: PageContainerProps<T>) {
  const Component = as ?? 'div';

  return (
    <Component className={cn('app-shell-container', className)} {...props}>
      {children}
    </Component>
  );
}
