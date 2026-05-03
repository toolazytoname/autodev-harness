import { motion } from 'framer-motion';

type ItemType = 'food' | 'toy' | 'book' | 'star' | 'trophy';

interface Item {
  id: string;
  name: string;
  type: ItemType;
  emoji: string;
  quantity: number;
  effect: string;
}

interface ItemButtonProps {
  item: Item;
  onClick?: () => void;
  disabled?: boolean;
}

export function ItemButton({ item, onClick, disabled = false }: ItemButtonProps) {
  return (
    <motion.button
      whileHover={!disabled ? { scale: 1.1 } : {}}
      whileTap={!disabled ? { scale: 0.95 } : {}}
      onClick={onClick}
      disabled={disabled || item.quantity === 0}
      className={`
        relative w-14 h-14 rounded-full flex items-center justify-center text-2xl
        transition-all duration-200
        ${
          disabled || item.quantity === 0
            ? 'bg-gray-200 opacity-50 cursor-not-allowed'
            : 'bg-surface shadow-card hover:shadow-hover cursor-pointer'
        }
      `}
      style={
        !disabled && item.quantity > 0
          ? { boxShadow: '0 4px 20px rgba(255, 155, 66, 0.15)' }
          : undefined
      }
    >
      <span>{item.emoji}</span>

      {/* Quantity Badge */}
      {item.quantity > 0 && (
        <span
          className={`
            absolute -top-1 -right-1 min-w-[20px] h-5 px-1.5
            flex items-center justify-center
            bg-primary text-white text-xs font-bold rounded-full
            ${item.quantity > 99 ? 'text-[10px]' : ''}
          `}
        >
          {item.quantity > 99 ? '99+' : item.quantity}
        </span>
      )}

      {/* Disabled Overlay */}
      {item.quantity === 0 && (
        <span className="absolute inset-0 flex items-center justify-center bg-gray-200/60 rounded-full">
          <span className="text-gray-400 text-lg">✕</span>
        </span>
      )}
    </motion.button>
  );
}
