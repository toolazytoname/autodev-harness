import { motion } from 'framer-motion';

interface NavItem {
  id: string;
  label: string;
  icon: string;
}

const navItems: NavItem[] = [
  { id: 'home', label: '首页', icon: '🏠' },
  { id: 'pets', label: '宠物', icon: '🐻' },
  { id: 'tasks', label: '任务', icon: '📋' },
  { id: 'profile', label: '我的', icon: '👤' },
];

interface BottomNavProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export function BottomNav({ activeTab, onTabChange }: BottomNavProps) {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-surface shadow-lg border-t border-primary/10 px-4 py-2 z-50">
      <div className="max-w-lg mx-auto flex justify-around items-center">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => onTabChange(item.id)}
            className="flex flex-col items-center gap-1 py-2 px-4 rounded-xl transition-colors"
          >
            <motion.span
              whileTap={{ scale: 0.9 }}
              className={`text-2xl ${activeTab === item.id ? 'opacity-100' : 'opacity-50'}`}
            >
              {item.icon}
            </motion.span>
            <span
              className={`text-xs font-medium ${
                activeTab === item.id ? 'text-primary' : 'text-text-light'
              }`}
            >
              {item.label}
            </span>
            {activeTab === item.id && (
              <motion.div
                layoutId="activeTab"
                className="w-1 h-1 rounded-full bg-primary"
              />
            )}
          </button>
        ))}
      </div>
    </nav>
  );
}
