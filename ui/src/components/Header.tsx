import { motion } from 'framer-motion';

interface HeaderProps {
  className?: string;
}

export function Header({ className = '' }: HeaderProps) {
  return (
    <header
      className={`sticky top-0 z-40 bg-surface/80 backdrop-blur-md border-b border-primary/10 px-4 py-3 ${className}`}
    >
      <div className="max-w-lg mx-auto flex items-center justify-between">
        {/* Logo */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          className="flex items-center gap-2"
        >
          <span className="text-3xl">🐻</span>
          <div>
            <h1 className="font-display text-xl font-bold text-primary">PetPal</h1>
            <p className="text-xs text-text-light">电子宠物奖励系统</p>
          </div>
        </motion.div>

        {/* Class Switcher & User */}
        <div className="flex items-center gap-3">
          {/* Class Switcher */}
          <button className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-secondary/20 text-text text-sm font-medium hover:bg-secondary/30 transition-colors">
            <span>🎓</span>
            <span className="hidden sm:inline">小熊班</span>
            <span>▼</span>
          </button>

          {/* User Avatar */}
          <button className="w-9 h-9 rounded-full bg-primary flex items-center justify-center text-white font-bold text-sm">
            T
          </button>
        </div>
      </div>
    </header>
  );
}
