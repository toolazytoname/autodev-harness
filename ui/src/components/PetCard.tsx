import { motion } from 'framer-motion';
import { ProgressBar } from './ProgressBar';

type PetType = 'bear' | 'bunny' | 'cat' | 'dog';
type PetState = 'normal' | 'hungry' | 'happy' | 'sleeping';

interface Pet {
  id: string;
  name: string;
  type: PetType;
  level: number;
  hunger: number;
  happiness: number;
  exp: number;
  expToNextLevel: number;
  state: PetState;
}

interface PetCardProps {
  pet: Pet;
  onClick?: () => void;
}

const petEmoji: Record<PetType, string> = {
  bear: '🐻',
  bunny: '🐰',
  cat: '🐱',
  dog: '🐶',
};

const petNames: Record<PetType, string> = {
  bear: '小熊维尼系',
  bunny: '小兔子系',
  cat: '小猫系',
  dog: '小狗系',
};

export function PetCard({ pet, onClick }: PetCardProps) {
  const stateEmoji: Record<PetState, string> = {
    normal: '',
    hungry: '😫',
    happy: '🥰',
    sleeping: '💤',
  };

  return (
    <motion.div
      whileHover={{ scale: 1.02, y: -4 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="bg-surface rounded-2xl p-4 shadow-card cursor-pointer"
      style={{ boxShadow: '0 4px 20px rgba(255, 155, 66, 0.15)' }}
    >
      {/* Pet Avatar */}
      <div className="flex items-center gap-4 mb-4">
        <motion.div
          animate={
            pet.state === 'happy'
              ? { y: [-4, 4, -4], rotate: [-5, 5, -5] }
              : pet.state === 'sleeping'
              ? { opacity: [1, 0.6, 1] }
              : {}
          }
          transition={{
            duration: pet.state === 'happy' ? 1 : 2,
            repeat: pet.state === 'happy' ? Infinity : Infinity,
            repeatType: 'reverse',
          }}
          className="relative"
        >
          <span className="text-6xl">
            {petEmoji[pet.type]}
            {stateEmoji[pet.state] && (
              <span className="absolute -top-2 -right-2 text-xl">
                {stateEmoji[pet.state]}
              </span>
            )}
          </span>
        </motion.div>

        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-display text-lg font-bold text-text">
              {pet.name}
            </h3>
            <span className="px-2 py-0.5 bg-secondary/20 rounded-full text-xs font-medium text-text">
              Lv.{pet.level}
            </span>
          </div>
          <p className="text-sm text-text-light">{petNames[pet.type]}</p>
        </div>
      </div>

      {/* Progress Bars */}
      <div className="space-y-3">
        <ProgressBar type="hunger" value={pet.hunger} size="sm" />
        <ProgressBar type="happiness" value={pet.happiness} size="sm" />
        <ProgressBar
          type="experience"
          value={pet.exp}
          max={pet.expToNextLevel}
          size="sm"
          showLabel={false}
        />
        <div className="flex justify-between text-xs text-text-light">
          <span>⭐ {pet.exp}/{pet.expToNextLevel}</span>
          <span>升级还需 {pet.expToNextLevel - pet.exp} 经验</span>
        </div>
      </div>
    </motion.div>
  );
}
