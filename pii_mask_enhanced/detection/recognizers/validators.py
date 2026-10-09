class Validator:
    @staticmethod
    def luhn_ok(num: str) -> bool:
        total = 0
        for i, c in enumerate(reversed(num)):
            d = int(c)
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return total % 10 == 0

    @staticmethod
    def inn_ok(num: str) -> bool:
        def ctrl(digs: str, koef: list[int]) -> int:
            return sum(int(d) * k for d, k in zip(digs, koef)) % 11 % 10

        if len(num) == 10:
            return ctrl(num[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8]) == int(num[9])
        if len(num) == 12:
            k11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
            k12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
            return ctrl(num[:10], k11) == int(num[10]) and ctrl(num[:11], k12) == int(num[11])
        return False


    @staticmethod
    def ogrn_ok(num: str) -> bool:
        if len(num) == 13:
            return int(num[:12]) % 11 % 10 == int(num[12])
        if len(num) == 15:
            return int(num[:14]) % 13 % 10 == int(num[14])
        return False

    @staticmethod
    def snils_ok(num: str) -> bool:
        if len(num) != 11:
            return False
        body, chk = num[:9], int(num[9:])
        s = sum(int(body[i]) * (9 - i) for i in range(9))
        if s < 100:
            expected = s
        elif s in (100, 101):
            expected = 0
        else:
            expected = s % 101
            if expected == 100:
                expected = 0
        return chk == expected

    @staticmethod
    def okpo_ok(num: str) -> bool:
        num = num.strip()
        if not num.isdigit() or len(num) not in (8, 10, 14):
            return False

        digits = [int(c) for c in num]
        body, check = digits[:-1], digits[-1]

        # веса идут по кругу 1..10: у ИП во втором проходе 9-я цифра - на 1, а не на 11
        def calc(start: int) -> int:
            return sum(d * ((start - 1 + i) % 10 + 1) for i, d in enumerate(body)) % 11

        rem = calc(1)
        if rem == 10:
            rem = calc(3)
            if rem == 10:
                rem = 0

        return rem == check