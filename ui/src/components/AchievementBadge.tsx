import { motion } from 'framer-motion';

interface Achievement {
  id: string;
  name: string;
  emoji: string;
  description: string;
  unlocked: boolean;
  unlockedAt?: string;
}

interface AchievementBadgeProps {
  achievement: Achievement;
  onClick?: () => void;
}

export function AchievementBadge({ achievement, onClick }: AchievementBadgeProps) {
  return (
    <motion.button
      whileHover={{ scale: 1.05, y: -2 }}
      whileTap={{ scale: 0.95 }}
      onClick={onClick}
      className="flex flex-col items-center gap-2 p-3 rounded-xl transition-all"
    >
      <div className="relative">
        {/* Badge Circle */}
        <motion.div
          animate={
            achievement.unlocked
              ? {
                  boxShadow: [
                    '0 0 0 0 rgba(255, 217, 61, 0.4)',
                    '0 0 0 8px rgba(255, 217, 61, 0)',
                  ],
                }
              : {}
          }
          transition={{ duration: 1.5, repeat: Infinity }}
          className={`
            w-16 h-16 rounded-full flex items-center justify-center text-3xl
            border-4
            ${
              achievement.unlocked
                ? 'bg-gradient-to-br from-yellow-300 to-yellow-500 border-yellow-400'
                : 'bg-gray-200 border-gray-300'
            }
          `}
        >
          <span className={achievement.unlocked ? '' : 'grayscale opacity-50'}>
            {achievement.unlocked ? achievement.emoji : '?'}
          </span>
        </motion.div>

        {/* Unlocked Glow */}
        {achievement.unlocked && (
          <div className="absolute inset-0 rounded-full bg-yellow-400/30 blur-md -z-10" />
        )}
      </div>

      {/* Name */}
      <span
        className={`text-sm font-medium text-center ${
          achievement.unlocked ? 'text-text' : 'text-text-light'
        }`}
      >
        {achievement.name}
      </span>
    </motion.button>
  );
}
