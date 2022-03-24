import d20

class Dice:
    def __init__(self, dice_str):
        """
        _summary_
        """
        self.dice_str = dice_str
        self.dice_result = d20.roll(self.dice_str)

    def roll(self):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        return self.dice_result.total
    
    def num(self, node = None):
        """
        _summary_

        Returns:
            _type_: _description_
        """
        total = 0
        if not node:
            node = self.dice_result.expr
        for child in node.children:
            if isinstance(child, d20.expression.Dice):
                total += child.num
            else:
                total += self.num(child)
        return total