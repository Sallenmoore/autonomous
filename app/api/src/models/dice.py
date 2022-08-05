import d20


class Dice:
    def __init__(self, dice_str, advantage=0):
        """
        creates a dice object from a dice str
        """
        self.dice_str = dice_str
        self.dice_result = d20.roll(self.dice_str, advantage)

    def roll_results(self):
        return {
            "dice_str":self.dice_result.result,
            "number": self.num(),
            "result": self.dice_result.total
        }
        

    def roll(self):
        """
        returns the total roll result

        Returns:
            int: 1-20
        """
        return self.dice_result.total

    def __filter_dice_str(self, key_str):
        """
        returns a list of indexes where the characters 
        can be found in the dice_str

        Args:
            key_str (_type_): _description_

        Returns:
            _type_: _description_
        """
        return list(filter(lambda x: x != -1, [self.dice_str.find(letter) for letter in key_str if letter in self.dice_str]))
    
    def num(self, node = None):
        """
        calculates the number of dice in the string

        Returns:
            int: number of dice
        """
        keep_drop = self.__filter_dice_str("kp")
        high_low = self.__filter_dice_str("hl")

        

        if keep_drop and high_low:
            return int(self.dice_str[high_low[0]+1])
        elif self.dice_str[0].isnumeric():
            return int(self.dice_str[0])

        total = 0
        if not node:
            node = self.dice_result.expr
        for child in node.children:
            if isinstance(child, d20.expression.Dice):
                total += child.num
            else:
                total += self.num(child)
        return total